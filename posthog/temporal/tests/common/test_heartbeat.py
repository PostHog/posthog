import dataclasses
from datetime import timedelta
from typing import Any

import pytest
from unittest import mock

from django.test import override_settings

from temporalio.testing import ActivityEnvironment

from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync


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
def test_heartbeater_sync_records_liveness_every_tick_while_the_first_heartbeat_waits(
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
