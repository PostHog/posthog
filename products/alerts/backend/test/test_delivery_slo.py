from unittest.mock import MagicMock, patch

from posthog.slo.types import SloOperation, SloOutcome

from products.alerts.backend.delivery_slo import alert_delivery_slo


@patch("products.alerts.backend.delivery_slo.get_instance_region", return_value="EU")
@patch("posthog.slo.context.emit_slo_completed")
@patch("posthog.slo.context.emit_slo_started")
def test_alert_delivery_slo_emits_shared_dimensions(
    mock_emit_started: MagicMock,
    mock_emit_completed: MagicMock,
    _mock_region: MagicMock,
) -> None:
    with alert_delivery_slo(
        alert_type="future_alert_type",
        notification_action="fire",
        distinct_id="alert-1",
        team_id=2,
        resource_id="alert-1",
        properties={"delivery_id": "delivery-1"},
    ) as slo:
        slo.fail(failure_phase="destination_enqueue")

    started = mock_emit_started.call_args.kwargs
    completed = mock_emit_completed.call_args.kwargs
    assert started["properties"].operation == SloOperation.ALERT_DELIVERY
    assert completed["properties"].outcome == SloOutcome.FAILURE
    assert completed["extra_properties"] == {
        "delivery_id": "delivery-1",
        "alert_type": "future_alert_type",
        "notification_action": "fire",
        "region": "EU",
        "correlation_id": started["extra_properties"]["correlation_id"],
        "failure_phase": "destination_enqueue",
    }
