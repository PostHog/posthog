import pytest

from temporalio.exceptions import (
    ActivityError,
    RetryState,
    TimeoutError as TemporalTimeoutError,
    TimeoutType,
)

from posthog.temporal.exports.types import ExportError, extract_error_details, is_user_query_export_error


def test_extract_error_details_classifies_temporal_activity_timeout() -> None:
    timeout = TemporalTimeoutError(
        "activity timed out",
        type=TimeoutType.HEARTBEAT,
        last_heartbeat_details=[],
    )
    activity_error = ActivityError(
        "activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="export-worker",
        activity_type="export_asset_activity",
        activity_id="export-1",
        retry_state=RetryState.MAXIMUM_ATTEMPTS_REACHED,
    )
    activity_error.__cause__ = timeout

    failure = extract_error_details(activity_error)

    assert failure is not None
    assert failure.exception_class == "TimeoutError"
    assert failure.failure_details == {
        "failure_category": "activity_timeout",
        "failure_component": "export_worker",
        "failure_retryable": True,
    }


@pytest.mark.parametrize(
    "error,expected",
    [
        (
            ExportError(
                exception_class="ValidationError",
                failure_details={
                    "failure_category": "application",
                    "failure_component": "exporter",
                    "failure_retryable": False,
                },
            ),
            False,
        ),
        (
            ExportError(
                exception_class="SyntaxError",
                failure_details={
                    "failure_category": "application",
                    "failure_component": "exporter",
                    "failure_retryable": False,
                },
            ),
            False,
        ),
        (
            ExportError(
                exception_class="ValidationError",
                failure_details={
                    "failure_category": "query",
                    "failure_component": "query",
                    "failure_retryable": False,
                },
            ),
            True,
        ),
        (ExportError(exception_class="ValidationError"), True),
    ],
    ids=["django_validation_error", "builtin_syntax_error", "drf_validation_error", "legacy_name_fallback"],
)
def test_is_user_query_export_error_uses_failure_metadata(error: ExportError, expected: bool) -> None:
    assert is_user_query_export_error(error) is expected
