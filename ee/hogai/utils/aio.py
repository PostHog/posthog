import time
import asyncio
import threading
from collections.abc import AsyncGenerator, Callable, Generator
from queue import Queue
from typing import Any, TypeVar

from django.conf import settings

import structlog
from prometheus_client import Histogram

logger = structlog.get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# Shared buckets for the "offloaded (de)serialization latency" histograms. The high end runs to
# 30s on purpose: the slow serializations this instrumentation exists to catch (the O(n^2)
# accumulated-message tail, see ee/hogai/stream/STREAMING_DELTAS_FOLLOWUP.md) can be multi-second,
# and a lower ceiling would dump them all into +Inf and saturate p99.
OFFLOAD_LATENCY_BUCKETS = [
    0.0005,
    0.001,
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    float("inf"),
]


async def run_maybe_offloaded(fn: Callable[[T], R], arg: T, *, histogram: Histogram) -> R:
    """Run a CPU-bound `fn(arg)`, optionally on a worker thread, and record how long it took.

    Gated by `settings.MAX_AI_STREAM_OFFLOAD_SERIALIZATION` (read per call so it stays
    toggleable at runtime and in tests). When enabled, the work runs via `asyncio.to_thread`.

    This does NOT give true CPU parallelism — under the GIL the worker thread still holds the
    interpreter lock for Python / pydantic-core work — but it lets the serving event loop preempt
    at the GIL switch interval instead of being blocked for the whole serialization, which is what
    keeps the dependency-free liveness probe answering under streaming load.

    Ordering is the caller's responsibility: await the result before yielding the next item.
    `histogram` must declare a single `offloaded` label; timing is observed in a `finally`, so
    failures are measured too (the loop was blocked for that time regardless of outcome).
    """
    offload = settings.MAX_AI_STREAM_OFFLOAD_SERIALIZATION
    start = time.perf_counter()
    try:
        if offload:
            return await asyncio.to_thread(fn, arg)
        return fn(arg)
    finally:
        histogram.labels(offloaded="true" if offload else "false").observe(time.perf_counter() - start)


def async_to_sync(async_handler: Callable[[], AsyncGenerator[Any, None]]) -> Generator[Any, None, None]:
    """Converts an async iterator to a sync generator."""

    q: Queue[Any] = Queue(maxsize=5000)
    sentinel = object()
    thread_exception = None

    async def runner():
        try:
            async for event in async_handler():
                q.put(event)
        except Exception as e:
            nonlocal thread_exception
            thread_exception = e
            q.put(sentinel)
        else:
            q.put(sentinel)

    def run_event_loop():
        asyncio.run(runner())

    # Use non-daemon thread with explicit cleanup
    thread = threading.Thread(target=run_event_loop, daemon=False)
    thread.start()

    try:
        # Yield items progressively as they arrive
        while True:
            item = q.get(timeout=60)  # Add timeout to prevent indefinite blocking. Matches max request TTL
            if item is sentinel:
                q.task_done()
                break

            yield item
            q.task_done()
    finally:
        # Ensure thread cleanup
        if thread.is_alive():
            # Signal thread to stop if possible, or wait briefly
            thread.join(timeout=1)
            if thread.is_alive():
                logger.warning("Thread did not terminate cleanly")

        if thread_exception:
            logger.error("Exception in async thread", exc_info=thread_exception)
