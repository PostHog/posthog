import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from django.test import override_settings

from temporalio.testing import ActivityEnvironment

from posthog.temporal.common.heartbeat import Heartbeater


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
