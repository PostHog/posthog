# This module is responsible for adding tags/metadata to outgoing clickhouse queries in a thread-safe manner

import threading
from typing import Any, Optional

thread_local_storage = threading.local()


def get_query_tags():
    try:
        return thread_local_storage.query_tags
    except AttributeError:
        return {}


def get_query_tag_value(key: str) -> Optional[Any]:
    try:
        return thread_local_storage.query_tags[key]
    except (AttributeError, KeyError):
        return None


def tag_queries(**kwargs):
    tags = {key: value for key, value in kwargs.items() if value is not None}
    try:
        thread_local_storage.query_tags.update(tags)
    except AttributeError:
        thread_local_storage.query_tags = tags


def reset_query_tags():
    thread_local_storage.query_tags = {}


class QueryCounter:
    def __init__(self):
        self.total_query_time = 0.0

    @property
    def query_time_ms(self):
        return self.total_query_time * 1000

    def __call__(self, execute, *args, **kwargs):
        import time

        start_time = time.perf_counter()

        try:
            return execute(*args, **kwargs)
        finally:
            self.total_query_time += time.perf_counter() - start_time
