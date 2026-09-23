"""Drive one activity failure through the PostHog interceptor and report whether it was captured."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.common import RetryPolicy
from temporalio.worker import ExecuteActivityInput

from posthog.dataclasses import frozen
from posthog.temporal.common.posthog_client import _PostHogClientActivityInboundInterceptor


@frozen
class ActivityInput:
    team_id: int


async def activity_under_test() -> None:
    """Stands in for the activity function, whose module and qualname the capture path reads."""


async def run_and_capture(error: Exception, *, attempt: int = 1, policy: RetryPolicy | None = None) -> MagicMock:
    next_interceptor = AsyncMock()
    next_interceptor.execute_activity.side_effect = error
    interceptor = _PostHogClientActivityInboundInterceptor(next_interceptor)

    mock_input = MagicMock(spec=ExecuteActivityInput)
    mock_input.args = [ActivityInput(team_id=1)]
    mock_input.fn = activity_under_test

    with (
        patch("posthog.temporal.common.posthog_client.api_key", "phc_test"),
        patch(
            "posthog.temporal.common.posthog_client.activity.info",
            return_value=MagicMock(attempt=attempt, retry_policy=policy),
        ),
        patch("posthog.temporal.common.posthog_client.capture_exception") as mock_capture,
    ):
        with pytest.raises(type(error)):
            await interceptor.execute_activity(mock_input)
    return mock_capture
