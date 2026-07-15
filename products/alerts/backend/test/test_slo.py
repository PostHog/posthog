from posthog.slo.types import SloArea, SloOperation

from products.alerts.backend.slo import build_alert_check_slo


def test_build_alert_check_slo_preserves_alert_identity_across_independent_event_properties() -> None:
    slo = build_alert_check_slo(
        team_id=42,
        alert_id="alert-1",
        distinct_id="user-1",
        alert_type="insight",
        properties={"calculation_interval": "daily", "insight_id": 123},
    )

    assert slo.operation == SloOperation.ALERT_CHECK
    assert slo.area == SloArea.ANALYTIC_PLATFORM
    assert slo.team_id == 42
    assert slo.resource_id == "alert-1"
    assert slo.distinct_id == "user-1"
    assert slo.start_properties == {
        "alert_type": "insight",
        "calculation_interval": "daily",
        "insight_id": 123,
    }
    assert slo.completion_properties == slo.start_properties

    slo.completion_properties["alert_state"] = "firing"
    assert "alert_state" not in slo.start_properties
