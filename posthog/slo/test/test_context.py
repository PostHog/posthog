import pytest
from unittest.mock import MagicMock, patch

from posthog.slo.context import SloSpec, slo_operation
from posthog.slo.types import SloArea, SloCompletedProperties, SloOperation, SloOutcome, SloStartedProperties


def _build_spec() -> SloSpec:
    return SloSpec(
        distinct_id="alert-123",
        area=SloArea.ANALYTIC_PLATFORM,
        operation=SloOperation.ALERT_CHECK,
        team_id=123,
        resource_id="alert-123",
    )


@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
def test_slo_operation_emits_success_with_completion_properties(
    mock_emit_slo_started: MagicMock, mock_emit_slo_completed: MagicMock
) -> None:
    capture = MagicMock()
    spec = _build_spec()

    with slo_operation(
        spec=spec,
        properties={"calculation_interval": "hourly"},
        capture=capture,
    ) as slo:
        slo.tag(alert_state="healthy", notifications_sent=2)

    mock_emit_slo_started.assert_called_once_with(
        distinct_id="alert-123",
        properties=SloStartedProperties(
            area=SloArea.ANALYTIC_PLATFORM,
            operation=SloOperation.ALERT_CHECK,
            team_id=123,
            resource_id="alert-123",
        ),
        extra_properties={"calculation_interval": "hourly"},
        capture=capture,
    )

    mock_emit_slo_completed.assert_called_once()
    completed_kwargs = mock_emit_slo_completed.call_args.kwargs
    assert completed_kwargs["distinct_id"] == "alert-123"
    assert completed_kwargs["properties"] == SloCompletedProperties(
        area=SloArea.ANALYTIC_PLATFORM,
        operation=SloOperation.ALERT_CHECK,
        team_id=123,
        outcome=SloOutcome.SUCCESS,
        resource_id="alert-123",
        duration_ms=completed_kwargs["properties"].duration_ms,
    )
    assert completed_kwargs["extra_properties"] == {
        "calculation_interval": "hourly",
        "alert_state": "healthy",
        "notifications_sent": 2,
    }
    assert completed_kwargs["capture"] is capture
    assert completed_kwargs["properties"].duration_ms is not None
    assert completed_kwargs["properties"].duration_ms >= 0


@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
def test_slo_operation_emits_failure_with_automatic_error_properties(
    mock_emit_slo_started: MagicMock, mock_emit_slo_completed: MagicMock
) -> None:
    capture = MagicMock()
    spec = _build_spec()

    with pytest.raises(RuntimeError, match="boom"):
        with slo_operation(
            spec=spec,
            properties={"calculation_interval": "daily"},
            capture=capture,
        ):
            raise RuntimeError("boom")

    mock_emit_slo_started.assert_called_once()
    mock_emit_slo_completed.assert_called_once()
    completed_kwargs = mock_emit_slo_completed.call_args.kwargs
    assert completed_kwargs["properties"].outcome == SloOutcome.FAILURE
    assert completed_kwargs["extra_properties"] == {
        "calculation_interval": "daily",
        "error_type": "RuntimeError",
        "error_message": "boom",
    }


@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
def test_slo_operation_allows_no_exception_failure_override(
    mock_emit_slo_started: MagicMock, mock_emit_slo_completed: MagicMock
) -> None:
    spec = _build_spec()

    with slo_operation(spec=spec, properties={"calculation_interval": "weekly"}) as slo:
        slo.fail(reason="partial_failure", failed_checks=1)

    mock_emit_slo_started.assert_called_once()
    mock_emit_slo_completed.assert_called_once()
    completed_kwargs = mock_emit_slo_completed.call_args.kwargs
    assert completed_kwargs["properties"].outcome == SloOutcome.FAILURE
    assert completed_kwargs["extra_properties"] == {
        "calculation_interval": "weekly",
        "reason": "partial_failure",
        "failed_checks": 1,
    }
