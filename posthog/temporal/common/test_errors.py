import pytest

from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError

from posthog.temporal.common.errors import (
    MAX_ERROR_MESSAGE_CHARS,
    MAX_ERROR_TRACE_CHARS,
    truncate_for_temporal_payload,
    unwrap_temporal_cause,
)


@pytest.mark.parametrize(
    "value,limit,expected",
    [
        # Short values pass through unchanged
        ("", 10, ""),
        ("short", 10, "short"),
        ("exactly10!", 10, "exactly10!"),
        # Long values are truncated with a diagnostic marker
        ("a" * 20, 10, "aaaaaaaaaa… (truncated, original 20 chars)"),
        # Limit of 0 is treated as "no content"
        ("anything", 0, "… (truncated, original 8 chars)"),
    ],
)
def test_truncate_for_temporal_payload(value, limit, expected):
    assert truncate_for_temporal_payload(value, limit) == expected


def test_default_limits_fit_under_temporal_payload_limit():
    # Temporal's hard limit is 2 MiB for the whole payload — activity metadata, input ref,
    # envelope framing, and our error strings all share that budget. Assert our error strings
    # fit inside 1 MiB (worst-case UTF-8: 4 bytes/char) to leave headroom for everything else.
    worst_case_error_bytes = (MAX_ERROR_MESSAGE_CHARS + MAX_ERROR_TRACE_CHARS) * 4
    assert worst_case_error_bytes < 1 * 1024 * 1024


def _activity_error(cause: BaseException) -> ActivityError:
    err = ActivityError(
        "activity failed",
        scheduled_event_id=1,
        started_event_id=2,
        identity="worker",
        activity_type="t",
        activity_id="a",
        retry_state=None,
    )
    err.__cause__ = cause
    return err


def _child_workflow_error(cause: BaseException) -> ChildWorkflowError:
    err = ChildWorkflowError(
        "child failed",
        namespace="default",
        workflow_id="w",
        run_id="r",
        workflow_type="t",
        initiated_event_id=1,
        started_event_id=2,
        retry_state=None,
    )
    err.__cause__ = cause
    return err


class TestUnwrapTemporalCause:
    def test_returns_none_for_bare_application_error(self) -> None:
        assert unwrap_temporal_cause(ApplicationError("x", type="X")) is None

    def test_returns_none_for_bare_exception(self) -> None:
        assert unwrap_temporal_cause(ValueError("x")) is None

    def test_unwraps_activity_error(self) -> None:
        leaf = ApplicationError("inner", type="X")
        assert unwrap_temporal_cause(_activity_error(leaf)) is leaf

    def test_unwraps_child_workflow_error_wrapping_activity_error(self) -> None:
        # Real Temporal chain when a child workflow's activity raises an ApplicationError.
        leaf = ApplicationError("inner", type="X")
        assert unwrap_temporal_cause(_child_workflow_error(_activity_error(leaf))) is leaf

    def test_returns_none_when_wrapper_chain_bottoms_out_on_non_application(self) -> None:
        assert unwrap_temporal_cause(_activity_error(ValueError("not an app error"))) is None
