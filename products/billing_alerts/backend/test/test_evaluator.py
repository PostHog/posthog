from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.billing_alerts.backend.logic.evaluator import evaluate_billing_alert
from products.billing_alerts.backend.logic.notifications import (
    evaluate_and_dispatch_billing_alert,
    preview_billing_alert,
)
from products.billing_alerts.backend.logic.state_machine import MAX_CONSECUTIVE_FAILURES
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)

DESTINATION_ID = "00000000-0000-0000-0000-000000000001"


def evaluate_and_record_billing_alert(*args, destination_ids: list[str] | None = None, **kwargs) -> BillingAlertEvent:
    """Exercise the production delivery-first pipeline with an acknowledged internal event.

    destination_ids defaults to one configured target; pass [] to simulate an alert with no
    destination configured, where the internal event is delivered but no user is notified.
    """
    ids = [DESTINATION_ID] if destination_ids is None else destination_ids
    with (
        patch(
            "products.billing_alerts.backend.logic.notifications.produce_alert_internal_event",
            return_value=MagicMock(),
        ),
        patch(
            "products.billing_alerts.backend.logic.notifications.alert_internal_event_delivered",
            return_value=True,
        ),
        patch(
            "products.billing_alerts.backend.logic.notifications._destination_ids",
            return_value=(ids, bool(ids)),
        ),
    ):
        event, _ = evaluate_and_dispatch_billing_alert(*args, **kwargs)
    return event


def _billing_response(
    current: str | int | float | None = None,
    *,
    projected: str | int | float | None = None,
    period_start: str = "2026-06-01T00:00:00Z",
    period_end: str = "2026-07-01T00:00:00Z",
    customer: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if customer is None:
        customer = {
            "has_active_subscription": True,
            "billing_period": {
                "current_period_start": period_start,
                "current_period_end": period_end,
                "interval": "month",
            },
            "current_total_amount_usd_after_discount": None if current is None else str(current),
            "projected_total_amount_usd_with_limit_after_discount": None if projected is None else str(projected),
        }
    return {"customer": customer}


class TestBillingAlertEvaluator(BaseTest):
    def _alert(self, **overrides) -> BillingAlertConfiguration:
        defaults = {
            "organization_id": self.organization.id,
            "team_id": self.team.id,
            "created_by_id": self.user.id,
            "name": "Period spend cap",
            "metric": BillingAlertConfiguration.Metric.SPEND,
            "threshold_type": BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE,
            "threshold_value": Decimal("100"),
            "minimum_value": Decimal("0"),
            "baseline_window_days": 7,
            "evaluation_delay_hours": 6,
        }
        defaults.update(overrides)
        return BillingAlertConfiguration.objects.create(**defaults)

    def test_absolute_value_breaches_on_current_period_spend(self) -> None:
        alert = self._alert()

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=_billing_response(120))

        assert evaluation.current_value == Decimal("120")
        assert evaluation.threshold_breached is True
        assert evaluation.payload["amount_field"] == "current_total_amount_usd_after_discount"
        assert evaluation.period_start == datetime(2026, 6, 1, tzinfo=UTC)
        assert evaluation.period_end == datetime(2026, 7, 1, tzinfo=UTC)

    def test_projected_spend_metric_reads_projected_period_total(self) -> None:
        alert = self._alert(metric=BillingAlertConfiguration.Metric.PROJECTED_SPEND)

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=_billing_response(40, projected=150))

        assert evaluation.current_value == Decimal("150")
        assert evaluation.threshold_breached is True
        assert evaluation.payload["amount_field"] == "projected_total_amount_usd_with_limit_after_discount"

    def test_value_below_threshold_does_not_breach(self) -> None:
        alert = self._alert()

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=_billing_response(70))

        assert evaluation.current_value == Decimal("70")
        assert evaluation.threshold_breached is False

    def test_value_below_minimum_never_breaches(self) -> None:
        alert = self._alert(minimum_value=Decimal("50"), threshold_value=Decimal("10"))

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=_billing_response(20))

        assert evaluation.threshold_breached is False
        assert "below the minimum" in evaluation.reason

    def test_missing_period_total_is_inconclusive(self) -> None:
        alert = self._alert()

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=_billing_response(None))

        assert evaluation.current_value is None
        assert evaluation.threshold_breached is False
        assert evaluation.is_inconclusive is True
        assert "did not include a spend total" in evaluation.reason

    def test_invalid_amount_records_error_event(self) -> None:
        alert = self._alert()

        event = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response("not-a-number"))
        alert.refresh_from_db()

        assert event.kind == BillingAlertEvent.Kind.ERRORED
        assert event.error_code == "BillingAlertEvaluationError"
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.consecutive_failures == 1

    def test_missing_customer_records_error_event(self) -> None:
        alert = self._alert()

        event = evaluate_and_record_billing_alert(alert, now=NOW, billing_response={"detail": "billing unavailable"})
        alert.refresh_from_db()

        assert event.kind == BillingAlertEvent.Kind.ERRORED
        assert alert.consecutive_failures == 1

    def test_repeated_error_escalates_to_broken_and_disables(self) -> None:
        alert = self._alert()
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1)

        event = evaluate_and_record_billing_alert(alert, now=NOW, billing_response={"detail": "still down"})
        alert.refresh_from_db()

        assert event.kind == BillingAlertEvent.Kind.BROKEN_CONFIG
        assert alert.state == BillingAlertConfiguration.State.BROKEN
        assert alert.enabled is False

    def test_state_machine_records_firing_then_resolved(self) -> None:
        alert = self._alert()

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response(120))
        alert.refresh_from_db()

        assert firing.kind == BillingAlertEvent.Kind.FIRING
        assert alert.state == BillingAlertConfiguration.State.FIRING
        assert alert.last_notified_at == NOW

        resolved = evaluate_and_record_billing_alert(
            alert, now=NOW.replace(day=24), billing_response=_billing_response(70)
        )
        alert.refresh_from_db()

        assert resolved.kind == BillingAlertEvent.Kind.RESOLVED
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING

    def test_completed_daily_evaluation_is_idempotent(self) -> None:
        alert = self._alert()

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response(120))
        repeated = evaluate_and_record_billing_alert(
            alert, now=NOW.replace(hour=13), billing_response=_billing_response(70)
        )

        assert repeated.id == firing.id
        assert (
            BillingAlertEvent.objects.filter(claim__alert=alert, claim__evaluation_date=firing.evaluation_date).count()
            == 1
        )

    def test_cooldown_suppresses_repeated_firing_notification(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.NOT_FIRING, cooldown_hours=48)

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response(120))
        alert.refresh_from_db()
        assert firing.kind == BillingAlertEvent.Kind.FIRING

        repeated = evaluate_and_record_billing_alert(
            alert, now=NOW.replace(day=24), billing_response=_billing_response(120)
        )
        alert.refresh_from_db()

        assert repeated.kind == BillingAlertEvent.Kind.CHECK
        assert repeated.threshold_breached is True
        assert alert.state == BillingAlertConfiguration.State.FIRING

    def test_zero_destinations_do_not_start_cooldown(self) -> None:
        alert = self._alert()

        firing = evaluate_and_record_billing_alert(
            alert, now=NOW, billing_response=_billing_response(120), destination_ids=[]
        )
        alert.refresh_from_db()

        # The alert still fires (internal event tracked), but with nothing delivered the
        # cooldown timestamp stays unset so a destination added later is not suppressed.
        assert firing.kind == BillingAlertEvent.Kind.FIRING
        assert alert.state == BillingAlertConfiguration.State.FIRING
        assert firing.notification_sent_at is None
        assert alert.last_notified_at is None

    def test_snoozed_alert_clears_to_resolved(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.SNOOZED)

        resolved = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response(70))
        alert.refresh_from_db()

        assert resolved.kind == BillingAlertEvent.Kind.RESOLVED
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING

    def test_preview_evaluates_without_persisting_or_dispatching(self) -> None:
        alert = self._alert(enabled=False)

        with patch("products.billing_alerts.backend.logic.notifications.produce_alert_internal_event") as produce_mock:
            preview = preview_billing_alert(alert, now=NOW, billing_response=_billing_response(120))

        assert preview.evaluation.threshold_breached is True
        assert preview.would_notify is True
        produce_mock.assert_not_called()
        assert BillingAlertEvent.objects.filter(claim__alert=alert).count() == 0
        assert not alert.evaluation_claims.exists()
