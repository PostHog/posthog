from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from posthog.test.base import BaseTest

from products.billing_alerts.backend.logic.evaluator import evaluate_billing_alert
from products.billing_alerts.backend.logic.state_machine import evaluate_and_record_billing_alert, event_should_dispatch
from products.billing_alerts.backend.models import (
    MAX_FAILURES_BEFORE_BROKEN,
    BillingAlertConfiguration,
    BillingAlertEvent,
)

NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def _billing_response(values: list[int | str]) -> dict[str, Any]:
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
        return BillingAlertConfiguration.objects.unscoped().create(**defaults)

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
        assert "Invalid billing value" in (event.error_message or "")
        assert alert.state == BillingAlertConfiguration.State.ERRORED

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
        assert "authentication_failed" in (event.error_message or "")
        assert event_should_dispatch(event) is True
        assert alert.state == BillingAlertConfiguration.State.ERRORED

    def test_billing_service_error_uses_latest_failure_count(self) -> None:
        alert = self._alert()
        BillingAlertConfiguration.objects.unscoped().filter(pk=alert.pk).update(
            consecutive_failures=MAX_FAILURES_BEFORE_BROKEN - 1
        )

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
        assert event_should_dispatch(event) is True
        assert alert.consecutive_failures == MAX_FAILURES_BEFORE_BROKEN
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
            now=NOW.replace(hour=13),
            billing_response=_billing_response([60, 60, 70]),
        )
        alert.refresh_from_db()

        assert resolved.kind == BillingAlertEvent.Kind.RESOLVED
        assert resolved.threshold_breached is False
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING

    def test_state_machine_records_fresh_same_day_refiring_event_after_resolved_event(self) -> None:
        alert = self._alert()

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        BillingAlertEvent.objects.unscoped().filter(pk=firing.pk).update(notification_sent_at=NOW)
        BillingAlertConfiguration.objects.unscoped().filter(pk=alert.pk).update(last_notified_at=NOW)
        alert.refresh_from_db()

        resolved_at = NOW.replace(hour=13)
        resolved = evaluate_and_record_billing_alert(
            alert,
            now=resolved_at,
            billing_response=_billing_response([60, 60, 70]),
        )
        BillingAlertEvent.objects.unscoped().filter(pk=resolved.pk).update(notification_sent_at=resolved_at)
        BillingAlertConfiguration.objects.unscoped().filter(pk=alert.pk).update(last_notified_at=resolved_at)
        alert.refresh_from_db()

        refiring = evaluate_and_record_billing_alert(
            alert,
            now=NOW.replace(hour=14),
            billing_response=_billing_response([60, 60, 100]),
        )
        alert.refresh_from_db()

        assert refiring.kind == BillingAlertEvent.Kind.FIRING
        assert refiring.id != firing.id
        assert refiring.notification_sent_at is None
        assert event_should_dispatch(refiring) is True
        assert alert.state == BillingAlertConfiguration.State.FIRING
        assert (
            BillingAlertEvent.objects.unscoped()
            .filter(
                alert=alert,
                kind=BillingAlertEvent.Kind.FIRING,
                evaluation_date=firing.evaluation_date,
            )
            .count()
            == 2
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
            BillingAlertEvent.objects.unscoped()
            .filter(
                alert=alert,
                kind=BillingAlertEvent.Kind.CHECK,
                evaluation_date=first_check.evaluation_date,
            )
            .count()
            == 1
        )

    def test_state_machine_records_resolved_event_after_snoozed_alert_clears(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.SNOOZED)

        resolved = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 70]))
        alert.refresh_from_db()

        assert resolved.kind == BillingAlertEvent.Kind.RESOLVED
        assert resolved.threshold_breached is False
        assert event_should_dispatch(resolved) is True
        assert alert.state == BillingAlertConfiguration.State.NOT_FIRING

    def test_cooldown_only_suppresses_repeated_firing_notifications(self) -> None:
        alert = self._alert(
            state=BillingAlertConfiguration.State.NOT_FIRING,
            last_notified_at=NOW.replace(hour=11),
            cooldown_hours=24,
        )

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        alert.refresh_from_db()

        assert firing.kind == BillingAlertEvent.Kind.FIRING
        assert alert.state == BillingAlertConfiguration.State.FIRING

        repeated = evaluate_and_record_billing_alert(
            alert,
            now=NOW.replace(hour=13),
            billing_response=_billing_response([60, 60, 100]),
        )
        alert.refresh_from_db()

        assert repeated.kind == BillingAlertEvent.Kind.CHECK
        assert repeated.threshold_breached is True
        assert alert.state == BillingAlertConfiguration.State.FIRING

    def test_state_machine_uses_locked_current_state_for_repeated_firing(self) -> None:
        alert = self._alert(state=BillingAlertConfiguration.State.NOT_FIRING, cooldown_hours=24)
        stale_alert = BillingAlertConfiguration.objects.unscoped().get(pk=alert.pk)

        firing = evaluate_and_record_billing_alert(alert, now=NOW, billing_response=_billing_response([60, 60, 100]))
        BillingAlertEvent.objects.unscoped().filter(pk=firing.pk).update(notification_sent_at=NOW)
        BillingAlertConfiguration.objects.unscoped().filter(pk=alert.pk).update(last_notified_at=NOW)

        repeated = evaluate_and_record_billing_alert(
            stale_alert,
            now=NOW.replace(hour=13),
            billing_response=_billing_response([60, 60, 100]),
        )

        assert repeated.kind == BillingAlertEvent.Kind.CHECK
        assert repeated.state_before == BillingAlertConfiguration.State.FIRING
        assert repeated.state_after == BillingAlertConfiguration.State.FIRING
        assert (
            BillingAlertEvent.objects.unscoped()
            .filter(alert_id=alert.pk, kind=BillingAlertEvent.Kind.FIRING, evaluation_date=firing.evaluation_date)
            .count()
            == 1
        )
