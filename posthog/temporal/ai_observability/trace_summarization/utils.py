"""Utility functions for trace summarization."""

from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any, ParamSpec, TypeVar

from posthog.sync import database_sync_to_async
from posthog.temporal.common.utils import get_asyncify_executor

_P = ParamSpec("_P")
_R = TypeVar("_R")


def format_datetime_for_clickhouse(iso_string: str) -> str:
    """Convert ISO format datetime string to ClickHouse-compatible format."""
    dt = datetime.fromisoformat(iso_string)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def on_worker_thread(func: Callable[_P, _R]) -> Callable[_P, Coroutine[Any, Any, _R]]:
    """Run a blocking call on the worker's thread pool, which the worker sizes to its activity slots.

    The event loop's default pool caps at the node's CPU count + 4 threads. On a small node, slots
    above that cap would wait for a thread during a long LLM or ClickHouse call.
    """
    return database_sync_to_async(func, thread_sensitive=False, executor=get_asyncify_executor())
