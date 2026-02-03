"""
Async-safe wrappers for posthoganalytics calls in Temporal workers.

The posthoganalytics SDK with sync_mode=True makes blocking HTTP calls.
When called from async contexts (like Temporal interceptors on the event loop),
these blocking calls prevent heartbeat coroutines from being processed,
causing TimeoutError in concurrent activities.

This module provides async wrappers that offload the blocking calls to a
thread pool, keeping the event loop responsive.
"""

import asyncio
import concurrent.futures
from typing import Any

import posthoganalytics

# Dedicated thread pool for posthoganalytics calls to avoid blocking the event loop.
# Using a small pool since these are fire-and-forget analytics calls.
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix="posthog-analytics",
)


def _capture_sync(
    distinct_id: str | None,
    event: str,
    properties: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """Synchronous capture - runs in thread pool."""
    try:
        posthoganalytics.capture(
            distinct_id=distinct_id,
            event=event,
            properties=properties,
            **kwargs,
        )
    except Exception:
        # Silently ignore analytics failures - they shouldn't affect the workflow
        pass


def _capture_exception_sync(
    exception: BaseException,
    **kwargs: Any,
) -> None:
    """Synchronous capture_exception - runs in thread pool."""
    try:
        posthoganalytics.capture_exception(exception, **kwargs)
    except Exception:
        # Silently ignore analytics failures - they shouldn't affect the workflow
        pass


async def capture_async(
    distinct_id: str | None,
    event: str,
    properties: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """
    Async-safe wrapper for posthoganalytics.capture().

    Offloads the blocking HTTP call to a thread pool so it doesn't block
    the event loop. This is fire-and-forget - errors are silently ignored.
    """
    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor,
        _capture_sync,
        distinct_id,
        event,
        properties,
    )


async def capture_exception_async(
    exception: BaseException,
    **kwargs: Any,
) -> None:
    """
    Async-safe wrapper for posthoganalytics.capture_exception().

    Offloads the blocking HTTP call to a thread pool so it doesn't block
    the event loop. This is fire-and-forget - errors are silently ignored.
    """
    loop = asyncio.get_running_loop()
    # We need to pass kwargs through, but run_in_executor doesn't support kwargs directly.
    # Use a lambda or functools.partial
    loop.run_in_executor(
        _executor,
        lambda: _capture_exception_sync(exception, **kwargs),
    )


def capture_in_background(
    distinct_id: str | None,
    event: str,
    properties: dict[str, Any] | None = None,
    **kwargs: Any,
) -> None:
    """
    Fire-and-forget capture that works from any context (sync or async).

    Submits the capture to the thread pool without waiting for completion.
    Use this from sync code that might be called during async operations.
    """
    _executor.submit(_capture_sync, distinct_id, event, properties)


def capture_exception_in_background(
    exception: BaseException,
    **kwargs: Any,
) -> None:
    """
    Fire-and-forget capture_exception that works from any context (sync or async).

    Submits the capture to the thread pool without waiting for completion.
    Use this from sync code that might be called during async operations.
    """
    _executor.submit(lambda: _capture_exception_sync(exception, **kwargs))
