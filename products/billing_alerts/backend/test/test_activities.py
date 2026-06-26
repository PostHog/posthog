from decimal import Decimal

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.temporal.billing_alerts.activities import _evaluate_billing_alerts
from posthog.temporal.billing_alerts.types import EvaluateBillingAlertBatchActivityInputs

from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent


def _billing_response(values: list[int]) -> dict:
    return {
        "status": "ok",
        "results": [
            {
                "id": 1,
                "label": "Total",
                "dates": ["2026-06-20", "2026-06-21", "2026-06-22"],
                "data": values,
            }
        ],
    }


class TestBillingAlertActivities(BaseTest):
    def _alert(self, **overrides) -> BillingAlertConfiguration:
        defaults = {
            "organization_id": self.organization.id,
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "name": "Daily spend spike",
            "metric": BillingAlertConfiguration.Metric.SPEND,
            "threshold_type": BillingAlertConfiguration.ThresholdType.RELATIVE_INCREASE,
            "threshold_percentage": Decimal("50"),
            "minimum_value": Decimal("0"),
            "baseline_window_days": 2,
            "evaluation_delay_hours": 6,
        }
        defaults.update(overrides)
        return BillingAlertConfiguration.objects.unscoped().create(**defaults)

    @freeze_time("2026-06-23T12:00:00Z")
    @patch("posthog.temporal.billing_alerts.activities.fetch_billing_data")
    def test_fetch_failure_records_alert_failures_and_continues_batch(self, mock_fetch_billing_data) -> None:
        failed_alert = self._alert(name="Spend alert")
        successful_alert = self._alert(
            name="Usage alert",
            metric=BillingAlertConfiguration.Metric.USAGE,
        )
        mock_fetch_billing_data.side_effect = [
            RuntimeError("billing unavailable"),
            (_billing_response([60, 60, 100]), 12),
        ]

        event_ids = _evaluate_billing_alerts(
            EvaluateBillingAlertBatchActivityInputs(alert_ids=[str(failed_alert.id), str(successful_alert.id)])
        )

        failed_alert.refresh_from_db()
        successful_alert.refresh_from_db()
        failed_event = BillingAlertEvent.objects.unscoped().get(alert=failed_alert)
        successful_event = BillingAlertEvent.objects.unscoped().get(alert=successful_alert)

        assert mock_fetch_billing_data.call_count == 2
        assert set(event_ids) == {str(failed_event.id), str(successful_event.id)}
        assert failed_event.kind == BillingAlertEvent.Kind.ERRORED
        assert failed_event.is_transient_error is True
        assert "billing unavailable" in (failed_event.error_message or "")
        assert failed_alert.state == BillingAlertConfiguration.State.ERRORED
        assert successful_event.kind == BillingAlertEvent.Kind.FIRING
        assert successful_alert.state == BillingAlertConfiguration.State.FIRING
