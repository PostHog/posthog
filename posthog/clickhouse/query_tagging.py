# This module is responsible for adding tags/metadata to outgoing clickhouse queries in a thread-safe manner

import threading

thread_local_storage = threading.local()


def get_query_tags():
    try:
        return thread_local_storage.query_tags
    except AttributeError:
        return {}


def tag_queries(**kwargs):
    try:
        thread_local_storage.query_tags.update(kwargs)
    except AttributeError:
        thread_local_storage.query_tags = kwargs


def reset_query_tags():
    thread_local_storage.query_tags = {}
