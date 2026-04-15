import asyncio
import datetime as dt

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.common.heartbeat import Heartbeater


@pytest.fixture
def mock_activity_info():
    info = MagicMock()
    info.heartbeat_timeout = dt.timedelta(seconds=10)
    return info


async def _block_forever():
    """Awaitable that blocks until cancelled, standing in for activity.wait_for_worker_shutdown()."""
    await asyncio.get_event_loop().create_future()


@pytest.fixture(autouse=True)
def _patch_wait_for_worker_shutdown():
    with patch(
        "posthog.temporal.common.heartbeat.activity.wait_for_worker_shutdown",
        side_effect=_block_forever,
    ):
        yield


class TestHeartbeater:
    @pytest.mark.asyncio
    async def test_heartbeat_loop_survives_exceptions(self, mock_activity_info):
        """The heartbeat loop must continue after a transient exception from activity.heartbeat()."""
        heartbeat_call_count = 0

        def mock_heartbeat(*args):
            nonlocal heartbeat_call_count
            heartbeat_call_count += 1
            if heartbeat_call_count == 1:
                raise RuntimeError("Transient network error")

        with (
            patch("posthog.temporal.common.heartbeat.activity.info", return_value=mock_activity_info),
            patch("posthog.temporal.common.heartbeat.activity.heartbeat", side_effect=mock_heartbeat),
        ):
            heartbeater = Heartbeater(details=("test",), factor=1000)
            async with heartbeater:
                # Wait enough for multiple heartbeat cycles (delay = 10s / 1000 = 0.01s)
                await asyncio.sleep(0.05)

        # First call raised, but loop continued and heartbeat was called again
        assert heartbeat_call_count >= 2

    @pytest.mark.asyncio
    async def test_heartbeat_loop_logs_exception(self, mock_activity_info):
        """The heartbeat loop must log exceptions from activity.heartbeat()."""
        with (
            patch("posthog.temporal.common.heartbeat.activity.info", return_value=mock_activity_info),
            patch(
                "posthog.temporal.common.heartbeat.activity.heartbeat",
                side_effect=RuntimeError("Transient error"),
            ),
        ):
            heartbeater = Heartbeater(details=("test",), factor=1000)
            heartbeater.logger = MagicMock()

            async with heartbeater:
                await asyncio.sleep(0.02)

        heartbeater.logger.exception.assert_any_call("Heartbeat failed")

    @pytest.mark.asyncio
    async def test_exit_heartbeat_survives_exception(self, mock_activity_info):
        """__aexit__ must not raise if the final heartbeat call fails."""
        with (
            patch("posthog.temporal.common.heartbeat.activity.info", return_value=mock_activity_info),
            patch(
                "posthog.temporal.common.heartbeat.activity.heartbeat",
                side_effect=RuntimeError("Server unavailable"),
            ),
        ):
            heartbeater = Heartbeater(details=("test",), factor=1000)
            heartbeater.logger = MagicMock()

            # Should not raise despite heartbeat failure on exit
            async with heartbeater:
                pass

            heartbeater.logger.exception.assert_called_with("Final heartbeat on exit failed")
