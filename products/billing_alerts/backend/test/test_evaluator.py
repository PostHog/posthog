from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.billing_alerts.backend.logic.evaluator import evaluate_billing_alert
from products.billing_alerts.backend.logic.notifications import evaluate_and_dispatch_billing_alert
from products.billing_alerts.backend.logic.state_machine import MAX_CONSECUTIVE_FAILURES
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def evaluate_and_record_billing_alert(*args, **kwargs) -> BillingAlertEvent:
    """Exercise the production delivery-first pipeline with an acknowledged internal event."""
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
            return_value=(["00000000-0000-0000-0000-000000000001"], True),
        ),
    ):
        event, _ = evaluate_and_dispatch_billing_alert(*args, **kwargs)
    return event


def _billing_response(
    values: list[int | str],
    dates: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "results": [
            {
                "id": 1,
                "label": "Total",
                "dates": dates or ["2026-06-20", "2026-06-21", "2026-06-22"],
                "data": values,
            }
        ],
    }


class TestBillingAlertEvaluator(BaseTest):
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
        return BillingAlertConfiguration.objects.create(**defaults)

    def test_relative_increase_breaches_expected_billing_day(self) -> None:
        alert = self._alert()

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))

        assert evaluation.evaluation_date.isoformat() == "2026-06-22"
        assert evaluation.current_value == Decimal("100")
        assert evaluation.baseline_value == Decimal("60")
        assert evaluation.threshold_breached is True
        assert evaluation.payload["expected_evaluation_date"] == "2026-06-22"

    def test_relative_increase_reason_describes_negative_delta_as_below_baseline(self) -> None:
        alert = self._alert()

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=_billing_response([80, 80, 60]))

        assert evaluation.relative_delta_percentage == Decimal("-25.000000")
        assert evaluation.threshold_breached is False
        assert "25.00% below baseline" in evaluation.reason

    def test_missing_expected_billing_day_does_not_fall_back_to_older_data(self) -> None:
        alert = self._alert()
        response = {
            "status": "ok",
            "results": [{"id": 1, "label": "Total", "dates": ["2026-06-20", "2026-06-21"], "data": [60, 60]}],
        }

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=response)

        assert evaluation.evaluation_date.isoformat() == "2026-06-22"
        assert evaluation.current_value is None
        assert evaluation.threshold_breached is False
        assert evaluation.is_inconclusive is True
        assert "not available yet" in evaluation.reason

    def test_partial_baseline_window_is_inconclusive_and_preserves_state(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.FIRING)
        response = {
            "status": "ok",
            "results": [{"id": 1, "label": "Total", "dates": ["2026-06-21", "2026-06-22"], "data": [60, 100]}],
        }

        event = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=response)
        alert.refresh_from_db()

        assert event.kind == BillingAlertEvent.Kind.CHECK
        assert event.threshold_breached is False
        assert event.payload["missing_baseline_dates"] == ["2026-06-20"]
        assert alert.state == BillingAlertConfiguration.State.FIRING

    def test_absolute_value_alerts_do_not_require_baseline_data(self) -> None:
        alert = self._alert(
            threshold_type=BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE,
            threshold_percentage=None,
            threshold_value=Decimal("100"),
        )
        response = {
            "status": "ok",
            "results": [{"id": 1, "label": "Total", "dates": ["2026-06-22"], "data": [100]}],
        }

        evaluation = evaluate_billing_alert(alert, now=NOW, billing_response=response)

        assert evaluation.threshold_breached is True
        assert evaluation.baseline_value is None
        assert evaluation.is_inconclusive is False

    def test_invalid_billing_cell_records_error_event(self) -> None:
        alert = self._alert()

        event = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, "bad", 100]))
        alert.refresh_from_db()

        assert event.kind == BillingAlertEvent.Kind.ERRORED
        assert event.error_code == "BillingAlertEvaluationError"
        assert event.error_message == "Billing alert evaluation failed."
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
        assert alert.consecutive_failures == 1

    def test_billing_service_error_records_dispatchable_error_event(self) -> None:
        alert = self._alert()

        event = evaluate_and_record_billing_alert(
            alert,
            now=NOW,
            billing_response={
                "type": "authentication_error",
                "code": "authentication_failed",
                "detail": "Authorization is invalid: Signature verification failed",
            },
        )
        alert.refresh_from_db()

        assert event.kind == BillingAlertEvent.Kind.ERRORED
        assert event.error_code == "BillingAlertEvaluationError"
        assert event.error_message == "Billing alert evaluation failed."
        assert event.notification_sent_at == NOW
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING

    def test_billing_service_error_preserves_existing_firing_episode(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.FIRING)

        event = evaluate_and_record_billing_alert(
            alert,
            now=NOW,
            billing_response={"status": "error", "detail": "billing unavailable"},
        )
        alert.refresh_from_db()

        assert event.kind == BillingAlertEvent.Kind.ERRORED
        assert event.state_before == BillingAlertConfiguration.State.FIRING
        assert event.state_after == BillingAlertConfiguration.State.FIRING
        assert alert.state == BillingAlertConfiguration.State.FIRING
        assert alert.consecutive_failures == 1

    def test_billing_service_error_uses_latest_failure_count(self) -> None:
        alert = self._alert()
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(consecutive_failures=MAX_CONSECUTIVE_FAILURES - 1)

        event = evaluate_and_record_billing_alert(
            alert,
            now=NOW,
            billing_response={
                "type": "authentication_error",
                "code": "authentication_failed",
                "detail": "Authorization is invalid: Signature verification failed",
            },
        )
        alert.refresh_from_db()

        assert event.kind == BillingAlertEvent.Kind.BROKEN_CONFIG
        assert event.notification_sent_at == NOW
        assert alert.consecutive_failures == MAX_CONSECUTIVE_FAILURES
        assert alert.state == BillingAlertConfiguration.State.BROKEN
        assert alert.enabled is False

    def test_state_machine_records_firing_and_resolved_events(self) -> None:
        alert = self._alert()

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        alert.refresh_from_db()

        assert firing.kind == BillingAlertEvent.Kind.FIRING
        assert firing.threshold_breached is True
        assert alert.state == BillingAlertConfiguration.State.FIRING

        resolved = evaluate_and_record_billing_alert(
            alert,
            now=NOW.replace(day=24),
            billing_response=_billing_response([60, 60, 70], ["2026-06-21", "2026-06-22", "2026-06-23"]),
        )
        alert.refresh_from_db()

        assert resolved.kind == BillingAlertEvent.Kind.RESOLVED
        assert resolved.threshold_breached is False
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING

    def test_completed_daily_evaluation_is_idempotent(self) -> None:
        alert = self._alert()

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        repeated = evaluate_and_record_billing_alert(
            alert,
            now=NOW.replace(hour=13),
            billing_response=_billing_response([60, 60, 70]),
        )

        assert repeated.id == firing.id
        assert (
            BillingAlertEvent.objects.filter(
                claim__alert=alert,
                claim__evaluation_date=firing.evaluation_date,
            ).count()
            == 1
        )

    def test_state_machine_reuses_same_day_check_event(self) -> None:
        alert = self._alert()

        first_check = evaluate_and_record_billing_alert(
            alert,
            now=NOW,
            billing_response=_billing_response([60, 60, 70]),
        )
        second_check = evaluate_and_record_billing_alert(
            alert,
            now=NOW.replace(hour=13),
            billing_response=_billing_response([60, 60, 65]),
        )

        assert first_check.kind == BillingAlertEvent.Kind.CHECK
        assert second_check.kind == BillingAlertEvent.Kind.CHECK
        assert second_check.id == first_check.id
        assert (
            BillingAlertEvent.objects.filter(
                claim__alert=alert,
                kind=BillingAlertEvent.Kind.CHECK,
                claim__evaluation_date=first_check.evaluation_date,
            ).count()
            == 1
        )

    def test_state_machine_records_resolved_event_after_snoozed_alert_clears(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.SNOOZED)

        resolved = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 70]))
        alert.refresh_from_db()

        assert resolved.kind == BillingAlertEvent.Kind.RESOLVED
        assert resolved.threshold_breached is False
        assert resolved.notification_sent_at == NOW
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING

    def test_cooldown_only_suppresses_repeated_firing_notifications(self) -> None:
        alert = self._alert(
            state=BillingAlertConfiguration.State.NOT_FIRING,
            last_notified_at=NOW.replace(hour=11),
            cooldown_hours=48,
        )

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        alert.refresh_from_db()

        assert firing.kind == BillingAlertEvent.Kind.FIRING
        assert alert.state == BillingAlertConfiguration.State.FIRING

        repeated = evaluate_and_record_billing_alert(
            alert,
            now=NOW.replace(day=24),
            billing_response=_billing_response([60, 60, 100], ["2026-06-21", "2026-06-22", "2026-06-23"]),
        )
        alert.refresh_from_db()

        assert repeated.kind == BillingAlertEvent.Kind.CHECK
        assert repeated.threshold_breached is True
        assert alert.state == BillingAlertConfiguration.State.FIRING

    def test_state_machine_uses_locked_current_state_for_repeated_firing(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.NOT_FIRING, cooldown_hours=48)
        stale_alert = BillingAlertConfiguration.objects.get(pk=alert.pk)

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        BillingAlertEvent.objects.filter(pk=firing.pk).update(notification_sent_at=NOW)
        BillingAlertConfiguration.objects.filter(pk=alert.pk).update(last_notified_at=NOW)

        repeated = evaluate_and_record_billing_alert(
            stale_alert,
            now=NOW.replace(day=24),
            billing_response=_billing_response([60, 60, 100], ["2026-06-21", "2026-06-22", "2026-06-23"]),
        )

        assert repeated.kind == BillingAlertEvent.Kind.CHECK
        assert repeated.state_before == BillingAlertConfiguration.State.FIRING
        assert repeated.state_after == BillingAlertConfiguration.State.FIRING
        assert (
            BillingAlertEvent.objects.filter(
                claim__alert_id=alert.pk,
                kind=BillingAlertEvent.Kind.FIRING,
                claim__evaluation_date=firing.evaluation_date,
            ).count()
            == 1
        )
