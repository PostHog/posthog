import asyncio
import threading
from collections.abc import Iterator

import pytest
from unittest import mock

from django.test import override_settings

from asgiref.sync import async_to_sync, sync_to_async

from posthog.temporal.common import thread_pools, utils, worker
from posthog.temporal.common.thread_pools import (
    DEFAULT_EXECUTOR_THREAD_NAME_PREFIX,
    WorkerThreadPoolSizes,
    WorkerThreadPoolTooSmallError,
)

TIMEOUT_SECONDS = 10.0


@pytest.fixture
def restore_asyncify_executor() -> Iterator[None]:
    previous = utils.get_asyncify_executor()
    try:
        yield
    finally:
        configured = utils.get_asyncify_executor()
        if configured is not previous and configured is not None:
            configured.shutdown(wait=False)
        utils._asyncify_executor = previous


async def _create_worker(max_concurrent_activities: int, require_nested_thread_capacity: bool = False) -> None:
    with (
        mock.patch.object(worker, "connect", new=mock.AsyncMock()),
        mock.patch.object(worker, "Worker"),
        mock.patch.object(worker, "CombinedMetricsServer"),
    ):
        await worker.create_worker(
            host="localhost",
            port=7233,
            metrics_port=0,
            namespace="test",
            task_queue="test-queue",
            workflows=[],
            activities=[],
            max_concurrent_activities=max_concurrent_activities,
            require_nested_thread_capacity=require_nested_thread_capacity,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cpu_count,activities",
    [
        # Python gives 5, 8 and 12 threads on these CPU counts, fewer than the activities each time.
        (1, 8),
        (4, 15),
        (8, 30),
    ],
)
async def test_every_activity_can_wait_for_a_nested_default_executor_job(
    restore_asyncify_executor: None, cpu_count: int, activities: int
) -> None:
    every_activity_holds_a_thread = threading.Barrier(activities)

    async def nested() -> str:
        return await asyncio.to_thread(lambda: threading.current_thread().name)

    def first_level() -> tuple[str, str]:
        # The barrier makes each activity hold a thread before any activity submits its nested job.
        every_activity_holds_a_thread.wait(timeout=TIMEOUT_SECONDS)
        return threading.current_thread().name, async_to_sync(nested)()

    with mock.patch.object(thread_pools.os, "process_cpu_count", return_value=cpu_count):
        await _create_worker(activities)

    try:
        threads = await asyncio.wait_for(
            asyncio.gather(*[sync_to_async(first_level, thread_sensitive=False)() for _ in range(activities)]),
            timeout=TIMEOUT_SECONDS,
        )
    finally:
        # Releases the held threads if the pool is too small, so a failure does not hang the interpreter at exit.
        every_activity_holds_a_thread.abort()

    assert len(threads) == activities
    assert all(name.startswith(DEFAULT_EXECUTOR_THREAD_NAME_PREFIX) for pair in threads for name in pair)


@pytest.mark.parametrize(
    "cpu_count,activities,max_threads,expected",
    [
        (8, 15, 128, 68),
        (4, 15, 128, 68),
        (8, 30, 128, 128),
        # The limit holds the pool below the need of a worker with many slots.
        (8, 300, 128, 128),
        # A worker never gets fewer threads than Python gives it on the node.
        (8, 1, 128, 12),
        (64, 2, 128, 32),
        (8, 15, 4, 12),
    ],
)
def test_default_executor_size_follows_the_activity_slots(
    cpu_count: int, activities: int, max_threads: int, expected: int
) -> None:
    with mock.patch.object(thread_pools.os, "process_cpu_count", return_value=cpu_count):
        sizes = WorkerThreadPoolSizes.for_concurrency(
            activities, max_asyncify_threads=32, max_default_executor_threads=max_threads
        )

    assert sizes.default_executor_threads == expected
    assert sizes.activity_threads == activities
    assert sizes.covers_nested_jobs is (expected >= activities * 4 + 8)


@pytest.mark.parametrize(
    "cpu_count,activities,max_threads",
    [
        (8, 31, 128),
        (4, 15, 8),
    ],
)
def test_a_worker_that_requires_nested_capacity_rejects_a_pool_below_the_need(
    cpu_count: int, activities: int, max_threads: int
) -> None:
    with (
        mock.patch.object(thread_pools.os, "process_cpu_count", return_value=cpu_count),
        pytest.raises(WorkerThreadPoolTooSmallError, match=f"max_concurrent_activities={activities}"),
    ):
        WorkerThreadPoolSizes.for_concurrency(
            activities,
            max_asyncify_threads=32,
            max_default_executor_threads=max_threads,
            require_nested_capacity=True,
        )


@pytest.mark.asyncio
async def test_create_worker_fails_when_the_limit_leaves_a_required_pool_below_the_need(
    restore_asyncify_executor: None,
) -> None:
    with (
        mock.patch.object(thread_pools.os, "process_cpu_count", return_value=4),
        override_settings(TEMPORAL_DEFAULT_EXECUTOR_MAX_WORKERS=16),
        pytest.raises(WorkerThreadPoolTooSmallError, match="TEMPORAL_DEFAULT_EXECUTOR_MAX_WORKERS"),
    ):
        await _create_worker(15, require_nested_thread_capacity=True)


@pytest.mark.parametrize("activities", [0, -1])
def test_non_positive_activity_slots_are_rejected(activities: int) -> None:
    with pytest.raises(ValueError, match="max_concurrent_activities must be at least 1"):
        WorkerThreadPoolSizes.for_concurrency(activities, max_asyncify_threads=32, max_default_executor_threads=128)
