"""Thread pool sizes for a Temporal worker process.

An async activity runs on the worker's event loop and sends blocking work to the loop's default
executor with `asyncio.to_thread`, `sync_to_async(thread_sensitive=False)` or
`database_sync_to_async_pool`. Some of that work calls `async_to_sync` from its thread. asgiref then
runs the coroutine on the worker's event loop, and each default-executor call in that coroutine
submits a nested job to the same pool while the first thread waits for it.

The pool deadlocks when first-level jobs hold every thread: each one waits for a nested job that has
no thread to run on. Python sizes the default executor as `min(32, os.process_cpu_count() + 4)`, so
a smaller node type can move the pool below the number of activities and make the deadlock
possible. The sizes here come from the worker's activity slots instead.
"""

from __future__ import annotations

import os
import asyncio
from concurrent.futures import ThreadPoolExecutor

from posthog.dataclasses import frozen

# The number of default-executor threads that one activity can hold in a chain of nested jobs.
# A nested job can itself call `async_to_sync` and wait for a job of its own, so the default
# executor must have more than one thread for each activity.
DEFAULT_EXECUTOR_THREADS_PER_ACTIVITY = 4
# Threads for the default-executor work that does not belong to an activity, such as the log producer.
DEFAULT_EXECUTOR_HEADROOM = 8

DEFAULT_EXECUTOR_THREAD_NAME_PREFIX = "temporal-default"


class WorkerThreadPoolTooSmallError(ValueError):
    pass


def cpu_based_default_executor_threads() -> int:
    """The size that Python gives an unsized `ThreadPoolExecutor`."""
    return min(32, (os.process_cpu_count() or 1) + 4)


@frozen
class WorkerThreadPoolSizes:
    max_concurrent_activities: int
    activity_threads: int
    asyncify_threads: int
    default_executor_threads: int
    required_default_executor_threads: int

    @property
    def covers_nested_jobs(self) -> bool:
        return self.default_executor_threads >= self.required_default_executor_threads

    @staticmethod
    def required_default_executor_threads_for(max_concurrent_activities: int) -> int:
        return max_concurrent_activities * DEFAULT_EXECUTOR_THREADS_PER_ACTIVITY + DEFAULT_EXECUTOR_HEADROOM

    @classmethod
    def for_concurrency(
        cls,
        max_concurrent_activities: int,
        *,
        max_asyncify_threads: int,
        max_default_executor_threads: int,
        require_nested_capacity: bool = False,
    ) -> WorkerThreadPoolSizes:
        """Size the pools for `max_concurrent_activities` activity slots.

        The default executor never gets fewer threads than Python gives it on this node, so no worker
        loses threads. `max_default_executor_threads` limits the growth, because each thread can
        hold a database connection. With `require_nested_capacity`, raise if that limit leaves the
        default executor below the need of the activity slots.
        """
        if max_concurrent_activities < 1:
            raise ValueError(f"max_concurrent_activities must be at least 1, got {max_concurrent_activities}")
        required = cls.required_default_executor_threads_for(max_concurrent_activities)
        default_executor_threads = max(
            cpu_based_default_executor_threads(), min(required, max_default_executor_threads)
        )
        if require_nested_capacity and default_executor_threads < required:
            raise WorkerThreadPoolTooSmallError(
                f"The default executor has {default_executor_threads} threads, but "
                f"max_concurrent_activities={max_concurrent_activities} needs at least {required} "
                f"({DEFAULT_EXECUTOR_THREADS_PER_ACTIVITY} for each activity plus {DEFAULT_EXECUTOR_HEADROOM}). "
                "Increase TEMPORAL_DEFAULT_EXECUTOR_MAX_WORKERS or decrease MAX_CONCURRENT_ACTIVITIES."
            )
        return cls(
            max_concurrent_activities=max_concurrent_activities,
            activity_threads=max_concurrent_activities,
            asyncify_threads=min(max_concurrent_activities, max_asyncify_threads),
            default_executor_threads=default_executor_threads,
            required_default_executor_threads=required,
        )


def install_default_executor(loop: asyncio.AbstractEventLoop, sizes: WorkerThreadPoolSizes) -> ThreadPoolExecutor:
    """Give `loop` a default executor of the planned size. The loop shuts the executor down when it closes."""
    executor = ThreadPoolExecutor(
        max_workers=sizes.default_executor_threads, thread_name_prefix=DEFAULT_EXECUTOR_THREAD_NAME_PREFIX
    )
    loop.set_default_executor(executor)
    return executor
