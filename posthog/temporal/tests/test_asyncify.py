import asyncio
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import pytest
from unittest import mock

from django.conf import settings

from posthog.temporal.common import utils, worker
from posthog.temporal.common.utils import asyncify, configure_asyncify_executor, get_asyncify_executor

pytestmark = pytest.mark.asyncio

BARRIER_TIMEOUT_SECONDS = 5


class ConfigureExecutor(Protocol):
    def __call__(self, max_workers: int) -> ThreadPoolExecutor: ...


@pytest.fixture
def asyncify_executor() -> Iterator[ConfigureExecutor]:
    previous = get_asyncify_executor()
    try:
        yield configure_asyncify_executor
    finally:
        configured = get_asyncify_executor()
        if configured is not previous and configured is not None:
            configured.shutdown(wait=False)
        utils._asyncify_executor = previous


async def test_asyncify_runs_on_the_configured_executor(asyncify_executor: ConfigureExecutor) -> None:
    asyncify_executor(2)

    @asyncify
    def current_thread_name() -> str:
        return threading.current_thread().name

    assert (await current_thread_name()).startswith("asyncify")


async def test_asyncify_runs_as_many_calls_as_the_executor_has_threads(
    asyncify_executor: ConfigureExecutor,
) -> None:
    asyncify_executor(4)
    barrier = threading.Barrier(4)

    @asyncify
    def wait_for_the_others() -> int:
        # Without a timeout a regression parks non-daemon threads here and hangs the interpreter on exit.
        return barrier.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    results = await asyncio.wait_for(
        asyncio.gather(*(wait_for_the_others() for _ in range(4))),
        timeout=BARRIER_TIMEOUT_SECONDS * 2,
    )

    assert sorted(results) == [0, 1, 2, 3]


async def test_asyncify_keeps_unrelated_calls_off_a_saturated_pool(asyncify_executor: ConfigureExecutor) -> None:
    # Guards the incident: calls blocked on a slow dependency filled the pool and stalled everything else.
    pool_size = 4
    occupied = threading.Barrier(pool_size + 1)
    release = threading.Event()

    asyncify_executor(pool_size + 1)

    @asyncify
    def block_until_released() -> None:
        occupied.wait(timeout=BARRIER_TIMEOUT_SECONDS)
        release.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    @asyncify
    def unrelated_call() -> str:
        return "done"

    saturating = [asyncio.create_task(block_until_released()) for _ in range(pool_size)]
    try:
        # Clears only once every blocker holds a thread, so the pool is provably saturated below.
        await asyncio.to_thread(occupied.wait, BARRIER_TIMEOUT_SECONDS)
        assert await asyncio.wait_for(unrelated_call(), timeout=BARRIER_TIMEOUT_SECONDS) == "done"
    finally:
        release.set()
        await asyncio.gather(*saturating)


async def test_asyncify_falls_back_to_the_default_executor() -> None:
    previous = get_asyncify_executor()
    utils._asyncify_executor = None

    @asyncify
    def answer() -> int:
        return 42

    try:
        assert await answer() == 42
    finally:
        utils._asyncify_executor = previous


@pytest.mark.parametrize(
    "max_concurrent_activities,expected_workers",
    [
        (7, 7),
        (None, settings.ASYNCIFY_MAX_WORKERS),
        (settings.ASYNCIFY_MAX_WORKERS + 10, settings.ASYNCIFY_MAX_WORKERS),
    ],
)
async def test_create_worker_sizes_the_pool_to_the_activity_slots(
    asyncify_executor: ConfigureExecutor,
    max_concurrent_activities: int | None,
    expected_workers: int,
) -> None:
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
        )

    configured = get_asyncify_executor()
    assert configured is not None
    assert configured._max_workers == expected_workers
