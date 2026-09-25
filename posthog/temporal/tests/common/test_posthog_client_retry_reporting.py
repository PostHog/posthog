import pytest

from parameterized import parameterized
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from posthog.temporal.common.errors import NonReportableWhileRetryingError
from posthog.temporal.tests.common.interceptor_harness import run_and_capture

_FOUR_ATTEMPTS = RetryPolicy(maximum_attempts=4)
_UNLIMITED_ATTEMPTS = RetryPolicy(maximum_attempts=0)
_EXCLUDED_TYPE = RetryPolicy(maximum_attempts=4, non_retryable_error_types=["TransientDependency"])


class _TransientDependencyError(NonReportableWhileRetryingError):
    pass


class _TransientApplicationError(ApplicationError, NonReportableWhileRetryingError):
    def __init__(self, non_retryable: bool = False) -> None:
        super().__init__("dependency at capacity", type="TransientDependency", non_retryable=non_retryable)


@pytest.mark.asyncio
class TestReportingDeferredUntilRetriesSpent:
    @parameterized.expand(
        [
            # A retry follows, so the attempt costs the user nothing and must not open an issue.
            ("first_of_four", _TransientDependencyError("busy"), 1, _FOUR_ATTEMPTS, False),
            ("third_of_four", _TransientDependencyError("busy"), 3, _FOUR_ATTEMPTS, False),
            ("marked_application_error", _TransientApplicationError(), 1, _FOUR_ATTEMPTS, False),
            # No retry follows, so waiting any longer would report nothing at all.
            ("last_of_four", _TransientDependencyError("busy"), 4, _FOUR_ATTEMPTS, True),
            (
                "non_retryable_application_error",
                _TransientApplicationError(non_retryable=True),
                1,
                _FOUR_ATTEMPTS,
                True,
            ),
            ("type_the_policy_excludes", _TransientApplicationError(), 1, _EXCLUDED_TYPE, True),
            ("unlimited_attempts", _TransientDependencyError("busy"), 1, _UNLIMITED_ATTEMPTS, True),
            ("no_retry_policy", _TransientDependencyError("busy"), 1, None, True),
            # An unmarked failure is a defect on every attempt, as before.
            ("unmarked_failure", ValueError("boom"), 1, _FOUR_ATTEMPTS, True),
        ]
    )
    async def test_reporting_waits_for_the_last_attempt(self, _name, error, attempt, policy, reported):
        mock_capture = await run_and_capture(error, attempt=attempt, policy=policy)
        assert mock_capture.call_count == (1 if reported else 0)
