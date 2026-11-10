import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from temporalio.testing import ActivityEnvironment

from posthog.temporal.common.heartbeat import Heartbeater


class ActivityFailed(Exception):
    pass


@pytest.mark.parametrize(
    "fail,expected_heartbeats",
    [
        (False, []),
        (True, [("cursor-1",)]),
    ],
)
async def test_heartbeater_sends_details_on_exit_only_when_the_activity_fails(
    fail: bool, expected_heartbeats: list[tuple[Any, ...]]
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

    if fail:
        with pytest.raises(ActivityFailed):
            await env.run(short_activity)
    else:
        await env.run(short_activity)

    assert heartbeats == expected_heartbeats
