import asyncio

from parameterized import parameterized
from temporalio.exceptions import ActivityError, ApplicationError, CancelledError, RetryState

from posthog.temporal.common.posthog_client import _is_already_captured_or_cancellation


def _activity_error(message: str = "boom") -> ActivityError:
    return ActivityError(
        message,
        scheduled_event_id=1,
        started_event_id=2,
        identity="test",
        activity_type="export_event_clickhouse_rows",
        activity_id="3",
        retry_state=RetryState.MAXIMUM_ATTEMPTS_EXCEEDED,
    )


class TestIsAlreadyCapturedOrCancellation:
    @parameterized.expand(
        [
            # A TaskGroup bundles the real activity failure with the CancelledErrors of the
            # siblings it cancelled - the whole group is noise at the workflow level.
            ("activity_plus_cancelled_siblings", ExceptionGroup("eg", [_activity_error(), CancelledError()]), True),
            ("all_cancelled", ExceptionGroup("eg", [CancelledError(), CancelledError()]), True),
            ("nested_group", ExceptionGroup("eg", [ExceptionGroup("inner", [_activity_error()])]), True),
            ("bare_activity_error", _activity_error(), True),
            ("bare_temporal_cancelled", CancelledError(), True),
            ("bare_asyncio_cancelled", asyncio.CancelledError(), True),
        ]
    )
    def test_suppressed(self, _name: str, exc: BaseException, expected: bool) -> None:
        assert _is_already_captured_or_cancellation(exc) is expected

    @parameterized.expand(
        [
            # A genuine workflow-code bug must still be reported, even when bundled with cancellations.
            ("group_with_real_bug", ExceptionGroup("eg", [_activity_error(), ValueError("real bug")]), False),
            ("bare_application_error", ApplicationError("workflow logic failed"), False),
            ("bare_value_error", ValueError("real bug"), False),
        ]
    )
    def test_reported(self, _name: str, exc: BaseException, expected: bool) -> None:
        assert _is_already_captured_or_cancellation(exc) is expected
