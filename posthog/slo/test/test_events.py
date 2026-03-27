from unittest.mock import MagicMock, patch

from posthog.slo.events import emit_slo_completed, emit_slo_started
from posthog.slo.types import SloArea, SloCompletedProperties, SloOperation, SloOutcome, SloStartedProperties


def _failing_capture(*args, **kwargs) -> None:
    raise RuntimeError("capture failed")


@patch("posthog.slo.events.capture_exception")
def test_emit_slo_started_reports_and_swallows_capture_failures(mock_capture_exception: MagicMock) -> None:
    emit_slo_started(
        distinct_id="alert-123",
        properties=SloStartedProperties(
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.ALERT_CHECK,
            team_id=123,
            resource_id="alert-123",
        ),
        capture=_failing_capture,
    )

    mock_capture_exception.assert_called_once()
    error = mock_capture_exception.call_args.args[0]
    assert isinstance(error, RuntimeError)
    assert str(error) == "capture failed"
    assert mock_capture_exception.call_args.kwargs["additional_properties"] == {
        "slo_emit_event": "slo_operation_started",
        "distinct_id": "alert-123",
        "area": SloArea.ANALYTIC_PLATFORM,
        "operation": SloOperation.ALERT_CHECK,
        "team_id": 123,
        "resource_id": "alert-123",
    }


@patch("posthog.slo.events.capture_exception")
def test_emit_slo_completed_reports_and_swallows_capture_failures(mock_capture_exception: MagicMock) -> None:
    emit_slo_completed(
        distinct_id="alert-123",
        properties=SloCompletedProperties(
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.ALERT_CHECK,
            team_id=123,
            outcome=SloOutcome.FAILURE,
            resource_id="alert-123",
            duration_ms=12.5,
        ),
        capture=_failing_capture,
    )

    mock_capture_exception.assert_called_once()
    error = mock_capture_exception.call_args.args[0]
    assert isinstance(error, RuntimeError)
    assert str(error) == "capture failed"
    assert mock_capture_exception.call_args.kwargs["additional_properties"] == {
        "slo_emit_event": "slo_operation_completed",
        "distinct_id": "alert-123",
        "area": SloArea.ANALYTIC_PLATFORM,
        "operation": SloOperation.ALERT_CHECK,
        "team_id": 123,
        "resource_id": "alert-123",
    }
