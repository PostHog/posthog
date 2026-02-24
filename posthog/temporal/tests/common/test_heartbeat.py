import typing
import asyncio
import datetime as dt
import dataclasses
import collections.abc

import pytest

import temporalio
import temporalio.client
import temporalio.common
import temporalio.activity

from posthog.temporal.common.heartbeat import Heartbeater


@temporalio.activity.defn
async def hearbeat_for(iterations: int, details: collections.abc.Sequence[typing.Any]):
    """Heartbeat in a loop using ``Heartbeater`` for ``iterations``."""
    async with Heartbeater(details):
        for _ in range(iterations):
            await asyncio.sleep(0)


@pytest.fixture
def captured_heartbeats(activity_environment):
    """Capture details from all calls to ``activity.heartbeat``."""
    captured = []

    def capture(*args):
        nonlocal captured
        captured.append(tuple(args))

    activity_environment.on_heartbeat = capture
    # Setting to 0 so that we basically heartbeat on every event loop iteration
    activity_environment.info = dataclasses.replace(
        activity_environment.info, heartbeat_timeout=dt.timedelta(seconds=0)
    )

    return captured


async def test_heartbeater_heartbeats_details(activity_environment, captured_heartbeats):
    """Test whether ``Heartbeater`` heartbeats expected details.

    And **ONLY** the expected details.
    """
    heartbeat_details = ("some", "details", 123)
    iterations = 5
    await activity_environment.run(hearbeat_for, iterations, heartbeat_details)

    assert len(captured_heartbeats) == iterations + 1  # Heartbeater calls heartbeat one more time on context exit
    assert all(captured_hearbeat == heartbeat_details for captured_hearbeat in captured_heartbeats)
