#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Purge bot for Telegram supergroups.
# This program is dedicated to the public domain under the CC0 license.
"""
Create a file named token.txt containing the API token on the first line.
https://core.telegram.org/bots#creating-a-new-bot

Usage:
Press Ctrl-C on the command line or send a signal to the process to stop the
bot.

Invite the bot to a supergroup, grant admins right (deleting messages suffices) and type /start, /lifetime or /stop.
"""

from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from datetime import datetime, timedelta
import telegram.error
import logging
import pickle
import re
import collections

TOKEN = open("token.txt", "r").readline().rstrip()

class DeltaEmpty(Exception):
    pass

regex = re.compile(r'((?P<days>\d+?)d)?((?P<hours>\d+?)hr)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?')

def parse_time(time_str):
    parts = regex.match(time_str)
    if not parts:
        return
    parts = parts.groupdict()
    time_params = {}
    for (name, param) in parts.items():
        if param:
            time_params[name] = int(param)
    return timedelta(**time_params)

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

class Store(collections.MutableMapping):
    def __init__(self, filename):
        self.filename = filename
        
        try:
            with open(filename, 'rb') as file:
                self.store = pickle.load(file)
        except FileNotFoundError:
            self.store = dict()

    def sync(self):
        with open(self.filename, 'wb') as file:
            pickle.dump(self.store, file)

    def close(self):
        self.sync()

    def __getitem__(self, key):
        return self.store[self.__keytransform__(key)]
    
    def __setitem__(self, key, value):
        self.store[self.__keytransform__(key)] = value
    
    def __delitem__(self, key):
        del self.store[self.__keytransform__(key)]
    
    def __iter__(self):
        return iter(self.store)
    
    def __len__(self):
        return len(self.store)
    
    def __keytransform__(self, key):
        return key


store = Store('store.db')

if not 'groups' in store:
    store['groups'] = dict()
    store.sync()


def purge(bot, chat_id, date):
    if not chat_id in store['groups']:
        return
    
    group = store['groups'][chat_id]

    if group['latest_deleted_message_id'] != None:
        delete_from = group['latest_deleted_message_id']
    else:
        delete_from = 0

    messages = sorted(filter(lambda m: date - m['date'] >= group['lifetime'], group['messages'].values()), key=lambda m: m['message_id'])

    logging.info("filtered: %s", messages)

    try:
        delete_through = messages[-1]['message_id']
    except IndexError:
        return

    try:
        lowest_message_id = messages[0]['message_id']
        if lowest_message_id < delete_from:
            delete_from = lowest_message_id
    except IndexError:
        pass

    exclude = []

    chat = bot.get_chat(chat_id)

    logging.info(chat)

    if chat['pinned_message']:
        exclude.append(chat['pinned_message']['message_id'])

    exclude = set(exclude)

    try:
        lowest_excluded = min(exclude)
    except ValueError:
        lowest_excluded = None

    logging.info("Purging %i through %i, excluding %s", delete_from, delete_through, exclude)
    logging.info("%s", str(group))

    to_delete = [i for i in range(delete_from, delete_through + 1) if i not in exclude]

    for message_id in to_delete:
        try:
            bot.delete_message(chat_id=chat_id, message_id=message_id)
        except telegram.error.BadRequest:
            pass

        try:
            del group['messages'][message_id]
        except KeyError:
            pass

        latest_deleted_message_id = message_id

        if lowest_excluded is not None and lowest_excluded < latest_deleted_message_id:
            latest_deleted_message_id = lowest_excluded

        group['latest_deleted_message_id'] = latest_deleted_message_id

    store.sync()


def user_is_admin(bot, update):
    administrators = bot.get_chat_administrators(chat_id=update.message.chat_id)
    admin_ids = set(x['user']['id'] for x in administrators)
    
    return update['message']['from_user']['id'] in admin_ids


def start(bot, update):
    if not user_is_admin(bot, update):
        return
    
    chat_id = update.message.chat_id

    if not chat_id in store['groups']:
        store['groups'][chat_id] = {'messages': dict(), 'latest_deleted_message_id': None, 'lifetime': timedelta(days=36500)}
        store.sync()
    
    update.message.reply_text("Auto purging activated")

    lifetime(bot, update)


def stop(bot, update):
    if not user_is_admin(bot, update):
        return

    chat_id = update.message.chat_id
    
    if chat_id in store['groups']:
        del store['groups'][chat_id]
        store.sync()
    
    update.message.reply_text("Auto purging deactivated")


def lifetime(bot, update):
    if not user_is_admin(bot, update):
        return

    chat_id = update.message.chat_id
    
    if not chat_id in store['groups']:
        update.message.reply_text("Run /start first!")
        return

    try:
        delta = parse_time(update.message.text.split()[1])
        if delta.total_seconds() == 0:
            raise DeltaEmpty
        store['groups'][chat_id]['lifetime'] = delta
        store.sync()

        update.message.reply_text("Message lifetime set to %s" % str(delta))
    except IndexError:
        update.message.reply_text("Current message lifetime is %s" % str(store['groups'][chat_id]['lifetime']))
    except KeyError:
        update.message.reply_text("Try: /lifetime 30d")
    except DeltaEmpty:
        update.message.reply_text("Sorry Dave, I can't let you do that.")

    purge(bot, chat_id, update.message.date)


def help(bot, update):
    update.message.reply_text('Help!')


def echo(bot, update):
    message_id = update.message.message_id
    chat_id = update.message.chat_id
    date = update.message.date
    
    if not chat_id in store['groups']:
        return
    
    if not message_id in store['groups'][chat_id]:
        store['groups'][chat_id]['messages'][message_id] = {'message_id': message_id, 'date': date}
        store.sync()

    purge(bot, chat_id, update.message.date)

def error(bot, update, error):
    logger.warn('Update "%s" caused error "%s"' % (update, error))


def main():
    # Create the EventHandler and pass it your bot's token.
    updater = Updater(TOKEN)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stop", stop))
    dp.add_handler(CommandHandler("lifetime", lifetime))
    dp.add_handler(CommandHandler("help", help))

    # on noncommand i.e message - echo the message on Telegram
    dp.add_handler(MessageHandler(Filters.text, echo))

    # log all errors
    dp.add_error_handler(error)

    # Start the Bot
    updater.start_polling()

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()


if __name__ == '__main__':
    main()
