from dataclasses import dataclass

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import InterfaceError, OperationalError

from parameterized import parameterized
from temporalio.worker import ExecuteActivityInput

from posthog.temporal.common.posthog_client import _PostHogClientActivityInboundInterceptor


@dataclass
class _Input:
    team_id: int


async def _run_and_capture(error: Exception) -> MagicMock:
    next_interceptor = AsyncMock()
    next_interceptor.execute_activity.side_effect = error
    interceptor = _PostHogClientActivityInboundInterceptor(next_interceptor)

    mock_input = MagicMock(spec=ExecuteActivityInput)
    mock_input.args = [_Input(team_id=1)]
    mock_input.fn = _run_and_capture

    with (
        patch("posthog.temporal.common.posthog_client.api_key", "phc_test"),
        patch("posthog.temporal.common.posthog_client.activity.info", return_value=MagicMock()),
        patch("posthog.temporal.common.posthog_client.capture_exception") as mock_capture,
    ):
        with pytest.raises(type(error)):
            await interceptor.execute_activity(mock_input)
    return mock_capture


@pytest.mark.asyncio
class TestTransientDatabaseErrorReporting:
    @parameterized.expand(
        [
            ("pool_wait_timeout", OperationalError("query_wait_timeout")),
            ("connection_dropped", OperationalError("server closed the connection unexpectedly")),
            ("interface_error", InterfaceError("connection failed")),
        ]
    )
    async def test_transient_db_errors_are_not_reported(self, _name, error):
        # Temporal retries the activity, so a burst of pool timeouts must not mint an issue each.
        mock_capture = await _run_and_capture(error)
        mock_capture.assert_not_called()

    async def test_other_database_errors_are_still_reported(self):
        mock_capture = await _run_and_capture(OperationalError("deadlock detected"))
        mock_capture.assert_called_once()
