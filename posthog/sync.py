# From django channels https://github.com/django/channels/blob/b6dc8c127d7bda3f5e5ae205332b1388818540c5/channels/db.py#L16

from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from time import time
from typing import Any, Optional, ParamSpec, TypeVar, Union, overload

from django.conf import settings
from django.db import close_old_connections

from asgiref.sync import SyncToAsync
from prometheus_client import Histogram
from structlog import get_logger

logger = get_logger(__name__)

# Prometheus metric to track database_sync_to_async execution time
DATABASE_SYNC_TO_ASYNC_TIME = Histogram(
    "database_sync_to_async_thread_sensitive_execution_time_seconds",
    "Time spent while executing database_sync_to_async operations in thread-sensitive mode",
    labelnames=["function_name"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, float("inf")),
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


class DatabaseSyncToAsync(SyncToAsync):
    """
    SyncToAsync version that cleans up old database connections when it exits.
    """

    async def __call__(self, *args, **kwargs):
        # Automatically captures Temporal logging context.
        start_time = time()
        try:
            return await super().__call__(*args, **kwargs)
        finally:
            # Record the execution time metric
            if self._thread_sensitive:
                execution_time = time() - start_time
                fun_name = getattr(self.func, "__name__", "unknown")
                DATABASE_SYNC_TO_ASYNC_TIME.labels(function_name=fun_name).observe(execution_time)

    def thread_handler(self, loop, *args, **kwargs):
        # Don't close the connection in tests
        if not settings.TEST:
            close_old_connections()
        try:
            return super().thread_handler(loop, *args, **kwargs)
        finally:
            # Don't close the connection in tests
            if not settings.TEST:
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
