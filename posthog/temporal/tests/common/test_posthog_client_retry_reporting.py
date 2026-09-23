import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from temporalio.common import RetryPolicy
from temporalio.worker import ExecuteActivityInput

from posthog.dataclasses import frozen
from posthog.temporal.common.errors import NonReportableWhileRetryingError
from posthog.temporal.common.posthog_client import _PostHogClientActivityInboundInterceptor

from products.replay_vision.backend.temporal.errors import FailureKind, ScannerFailureError


@frozen
class _Input:
    team_id: int


async def _run_and_capture(error: Exception, *, attempt: int, policy: RetryPolicy | None) -> MagicMock:
    next_interceptor = AsyncMock()
    next_interceptor.execute_activity.side_effect = error
    interceptor = _PostHogClientActivityInboundInterceptor(next_interceptor)

    mock_input = MagicMock(spec=ExecuteActivityInput)
    mock_input.args = [_Input(team_id=1)]
    mock_input.fn = _run_and_capture

    activity_info = MagicMock(attempt=attempt, retry_policy=policy)
    with (
        patch("posthog.temporal.common.posthog_client.api_key", "phc_test"),
        patch("posthog.temporal.common.posthog_client.activity.info", return_value=activity_info),
        patch("posthog.temporal.common.posthog_client.capture_exception") as mock_capture,
    ):
        with pytest.raises(type(error)):
            await interceptor.execute_activity(mock_input)
    return mock_capture


_FOUR_ATTEMPTS = RetryPolicy(maximum_attempts=4)


@pytest.mark.asyncio
class TestReportingDeferredUntilRetriesSpent:
    @parameterized.expand([("first", 1), ("second", 2), ("third", 3)])
    async def test_retryable_failure_below_the_budget_is_not_reported(self, _name, attempt):
        # The scan recovers on a later attempt, so an issue per attempt would overstate the lost scans.
        error = ScannerFailureError("provider at capacity", kind=FailureKind.PROVIDER_TRANSIENT)
        mock_capture = await _run_and_capture(error, attempt=attempt, policy=_FOUR_ATTEMPTS)
        mock_capture.assert_not_called()

    async def test_last_attempt_is_reported(self):
        error = ScannerFailureError("provider at capacity", kind=FailureKind.PROVIDER_TRANSIENT)
        mock_capture = await _run_and_capture(error, attempt=4, policy=_FOUR_ATTEMPTS)
        mock_capture.assert_called_once()

    async def test_non_retryable_kind_is_reported_on_the_first_attempt(self):
        # No retry follows it, so deferring the report would drop it.
        error = ScannerFailureError("model refused the video", kind=FailureKind.PROVIDER_REJECTED)
        mock_capture = await _run_and_capture(error, attempt=1, policy=_FOUR_ATTEMPTS)
        mock_capture.assert_called_once()

    @parameterized.expand(
        [
            ("unlimited_attempts", RetryPolicy(maximum_attempts=0)),
            ("no_policy", None),
        ]
    )
    async def test_a_budget_without_a_last_attempt_is_reported(self, _name, policy):
        # Without a bound there is no last attempt to defer to, so waiting would report nothing at all.
        error = ScannerFailureError("provider at capacity", kind=FailureKind.PROVIDER_TRANSIENT)
        mock_capture = await _run_and_capture(error, attempt=1, policy=policy)
        mock_capture.assert_called_once()

    async def test_a_type_the_policy_excludes_is_reported_on_the_first_attempt(self):
        error = ScannerFailureError("provider at capacity", kind=FailureKind.PROVIDER_TRANSIENT)
        policy = RetryPolicy(maximum_attempts=4, non_retryable_error_types=["ScannerFailure"])
        mock_capture = await _run_and_capture(error, attempt=1, policy=policy)
        mock_capture.assert_called_once()

    async def test_an_unmarked_failure_is_reported_on_every_attempt(self):
        # Only a failure that opts in defers; a plain exception is a defect on each attempt.
        mock_capture = await _run_and_capture(ValueError("boom"), attempt=1, policy=_FOUR_ATTEMPTS)
        mock_capture.assert_called_once()

    async def test_the_marker_covers_a_plain_exception(self):
        class _TransientDependencyError(NonReportableWhileRetryingError):
            pass

        mock_capture = await _run_and_capture(_TransientDependencyError("busy"), attempt=1, policy=_FOUR_ATTEMPTS)
        mock_capture.assert_not_called()
