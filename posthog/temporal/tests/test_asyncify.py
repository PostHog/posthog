import asyncio
import threading
import dataclasses
from datetime import timedelta
from typing import Any

import pytest
from unittest import mock

from django.conf import settings
from django.test import override_settings

from temporalio.testing import ActivityEnvironment

from posthog.temporal.common import utils, worker
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.utils import asyncify, get_asyncify_executor, on_asyncify_pool
from posthog.temporal.tests.utils.asyncify import ConfigureExecutor

pytestmark = pytest.mark.asyncio

BARRIER_TIMEOUT_SECONDS = 5


@on_asyncify_pool
def _thread_name_decorated_at_import() -> str:
    return threading.current_thread().name


async def test_on_asyncify_pool_uses_the_pool_configured_after_decoration(asyncify_executor: ConfigureExecutor) -> None:
    asyncify_executor(2)

    assert (await _thread_name_decorated_at_import()).startswith("asyncify")


@pytest.mark.parametrize(
    "helper,submit_start_end,expect_warning",
    [
        ("on_asyncify_pool", (0.0, 0.0, 5.0), False),
        ("on_asyncify_pool", (0.0, 5.0, 5.0), True),
        ("asyncify", (0.0, 0.0, 5.0), True),
        ("asyncify", (0.0, 5.0, 5.0), True),
    ],
)
async def test_slow_call_warning(
    caplog: pytest.LogCaptureFixture, helper: str, submit_start_end: tuple[float, float, float], expect_warning: bool
) -> None:
    def blocking_call() -> None:
        return None

    wrapped = on_asyncify_pool(blocking_call) if helper == "on_asyncify_pool" else asyncify(blocking_call)
    clock = mock.Mock(monotonic=mock.Mock(side_effect=submit_start_end))

    with mock.patch.object(utils, "time", clock), caplog.at_level("WARNING"):
        await ActivityEnvironment().run(wrapped)

    assert any("asyncify_slow" in record.getMessage() for record in caplog.records) is expect_warning


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


async def test_asyncify_delivers_heartbeater_sync_heartbeats_on_the_event_loop() -> None:
    loop_thread = threading.get_ident()
    heartbeat_threads: list[int] = []
    heartbeat_seen = threading.Event()

    def record_heartbeat(*details: Any) -> None:
        heartbeat_threads.append(threading.get_ident())
        heartbeat_seen.set()

    @asyncify
    def heartbeat_from_a_worker_thread() -> bool:
        with HeartbeaterSync(factor=10):
            return heartbeat_seen.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, heartbeat_timeout=timedelta(seconds=1))
    env.on_heartbeat = record_heartbeat

    assert await env.run(heartbeat_from_a_worker_thread)
    assert set(heartbeat_threads) == {loop_thread}


async def test_asyncify_reports_a_heartbeat_the_sdk_rejects_on_the_event_loop() -> None:
    warned = threading.Event()
    logger = mock.MagicMock()
    logger.warning.side_effect = lambda *args, **kwargs: warned.set()
    tracker = mock.MagicMock()

    def reject_heartbeat(*details: Any) -> None:
        raise RuntimeError("heartbeat rejected")

    @asyncify
    def heartbeat_from_a_worker_thread() -> bool:
        with HeartbeaterSync(factor=10, logger=logger):
            return warned.wait(timeout=BARRIER_TIMEOUT_SECONDS)

    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, heartbeat_timeout=timedelta(seconds=1))
    env.on_heartbeat = reject_heartbeat

    with mock.patch("posthog.temporal.common.heartbeat_sync.get_liveness_tracker", return_value=tracker):
        assert await env.run(heartbeat_from_a_worker_thread)

    assert logger.warning.call_args.kwargs["error"] == "heartbeat rejected"
    tracker.record_heartbeat.assert_not_called()


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


class ActivityFailed(Exception):
    pass


@pytest.mark.parametrize(
    "skip_short_runs,fail,expected_heartbeats",
    [
        (True, False, []),
        (True, True, [("cursor-1",)]),
        (False, False, [("cursor-1",)]),
        (False, True, [("cursor-1",)]),
    ],
)
async def test_heartbeater_exit_heartbeat(
    skip_short_runs: bool, fail: bool, expected_heartbeats: list[tuple[Any, ...]]
) -> None:
    heartbeats: list[tuple[Any, ...]] = []

    async def short_activity() -> None:
        async with Heartbeater() as heartbeater:
            heartbeater.details = ("cursor-1",)
            if fail:
                raise ActivityFailed()

    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, heartbeat_timeout=timedelta(minutes=2))
    env.on_heartbeat = lambda *details: heartbeats.append(details)

    with override_settings(TEMPORAL_HEARTBEAT_SKIP_SHORT_RUNS=skip_short_runs):
        if fail:
            with pytest.raises(ActivityFailed):
                await env.run(short_activity)
        else:
            await env.run(short_activity)

    assert heartbeats == expected_heartbeats


class StopAfterWaits:
    def __init__(self, waits: int) -> None:
        self.waits_left = waits

    def is_set(self) -> bool:
        return self.waits_left <= 0

    def wait(self, timeout: float) -> bool:
        self.waits_left -= 1
        return self.is_set()


@pytest.mark.parametrize(
    "initial_delay,expected_sends",
    [
        (0.0, 5),
        (3.0, 2),
    ],
)
async def test_heartbeater_sync_records_liveness_every_tick_while_the_first_heartbeat_waits(
    initial_delay: float, expected_sends: int
) -> None:
    tracker = mock.MagicMock()
    send = mock.MagicMock()

    with (
        mock.patch("posthog.temporal.common.heartbeat_sync.get_liveness_tracker", return_value=tracker),
        mock.patch("posthog.temporal.common.heartbeat_sync.activity.heartbeat", send),
    ):
        HeartbeaterSync().heartbeat_regularly(
            StopAfterWaits(5),  # type: ignore[arg-type]
            interval=1.0,
            details=(),
            initial_delay=initial_delay,
        )

    assert send.call_count == expected_sends
    assert tracker.record_heartbeat.call_count == 5
