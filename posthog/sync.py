# From django channels https://github.com/django/channels/blob/b6dc8c127d7bda3f5e5ae205332b1388818540c5/channels/db.py#L16

from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import (
    Any,
    Optional,
    ParamSpec,
    TypeVar,
    Union,
    overload,
)

from asgiref.sync import SyncToAsync
from django.db import close_old_connections

_P = ParamSpec("_P")
_R = TypeVar("_R")


class DatabaseSyncToAsync(SyncToAsync):
    """
    SyncToAsync version that cleans up old database connections when it exits.
    """

    def thread_handler(self, loop, *args, **kwargs):
        close_old_connections()
        try:
            return super().thread_handler(loop, *args, **kwargs)
        finally:
            close_old_connections()


# Taken from https://github.com/django/asgiref/blob/main/asgiref/sync.py#L547
@overload
def database_sync_to_async(
    *,
    thread_sensitive: bool = True,
    executor: Optional["ThreadPoolExecutor"] = None,
) -> Callable[[Callable[_P, _R]], Callable[_P, Coroutine[Any, Any, _R]]]: ...


@overload
def database_sync_to_async(
    func: Callable[_P, _R],
    *,
    thread_sensitive: bool = True,
    executor: Optional["ThreadPoolExecutor"] = None,
) -> Callable[_P, Coroutine[Any, Any, _R]]: ...


def database_sync_to_async(
    func: Optional[Callable[_P, _R]] = None,
    *,
    thread_sensitive: bool = True,
    executor: Optional["ThreadPoolExecutor"] = None,
) -> Union[
    Callable[[Callable[_P, _R]], Callable[_P, Coroutine[Any, Any, _R]]],
    Callable[_P, Coroutine[Any, Any, _R]],
]:
    if func is None:
        return lambda f: DatabaseSyncToAsync(
            f,
            thread_sensitive=thread_sensitive,
            executor=executor,
        )
    return DatabaseSyncToAsync(
        func,
        thread_sensitive=thread_sensitive,
        executor=executor,
    )
