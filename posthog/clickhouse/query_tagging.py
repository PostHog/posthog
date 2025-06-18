# This module is responsible for adding tags/metadata to outgoing clickhouse queries in a thread-safe manner

import threading
from typing import Any, Optional
from collections.abc import Generator
from contextlib import contextmanager

from cachetools import cached

thread_local_storage = threading.local()


@cached(cache={})
def get_constant_tags():
    # import locally to avoid circular imports
    from posthog.git import get_git_commit_short
    from posthog.settings import CONTAINER_HOSTNAME, TEST, OTEL_SERVICE_NAME

    if TEST:
        return {
            "git_commit": "test",
            "container_hostname": "test",
            "service_name": "test",
        }

    return {
        "git_commit": get_git_commit_short(),
        "container_hostname": CONTAINER_HOSTNAME,
        "service_name": OTEL_SERVICE_NAME,
    }


def get_query_tags():
    try:
        tags = thread_local_storage.query_tags
    except AttributeError:
        tags = {}
    return {**tags, **get_constant_tags()}


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


def clear_tag(key):
    try:
        thread_local_storage.query_tags.pop(key, None)
    except AttributeError:
        pass


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


@contextmanager
def tags_context(**tags_to_set: Any) -> Generator[None, None, None]:
    """
    Context manager that saves all query tags on enter and restores them on exit.
    Optionally accepts key-value pairs to set after saving the original tags.

    Usage:
    ```python
    with tags_context(foo='bar', baz='qux'):
        # tags are saved, new tags are set
        # do stuff with tags
        # tags will be restored to original state after context
    ```
    """
    try:
        original_tags = dict(get_query_tags())  # Make a copy of current tags
        if tags_to_set:
            tag_queries(**tags_to_set)
        yield
    finally:
        thread_local_storage.query_tags = original_tags
