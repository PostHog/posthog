from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from products.billing_alerts.backend.logic.evaluator import BillingAlertEvaluation
from products.billing_alerts.backend.logic.state_machine import (
    apply_outcome,
    evaluate_alert_check,
    evaluate_alert_failure,
    next_billing_alert_check_at,
)
from products.billing_alerts.backend.models import BillingAlertConfiguration

from common.alerting.state_machine import AlertSnapshot, AlertState, NotificationAction

NOW = datetime(2026, 6, 23, 12, 30, tzinfo=UTC)


def _snapshot(**overrides) -> AlertSnapshot:
    defaults = {
        "state": AlertState.NOT_FIRING,
        "cooldown": timedelta(hours=24),
        "last_notified_at": None,
        "snooze_until": None,
        "consecutive_failures": 0,
    }
    defaults.update(overrides)
    return AlertSnapshot(**defaults)


def _evaluation(*, breached: bool, inconclusive: bool = False) -> BillingAlertEvaluation:
    return BillingAlertEvaluation(
        evaluation_date=date(2026, 6, 22),
        period_start=datetime(2026, 6, 22, tzinfo=UTC),
        period_end=datetime(2026, 6, 23, tzinfo=UTC),
        current_value=Decimal("100"),
        baseline_value=Decimal("60"),
        absolute_delta=Decimal("40"),
        relative_delta_percentage=Decimal("66.67"),
        threshold_breached=breached,
        reason="test",
        payload={},
        is_inconclusive=inconclusive,
    )


def test_failure_preserves_firing_state_and_counts_transient_errors() -> None:
    outcome = evaluate_alert_failure(
        _snapshot(state=AlertState.FIRING),
        error_message="billing unavailable",
        is_transient_error=True,
    )

    assert outcome.new_state == AlertState.FIRING
    assert outcome.notification == NotificationAction.ERROR
    assert outcome.consecutive_failures == 1


def test_fifth_failure_breaks_and_disables_alert_through_adapter() -> None:
    outcome = evaluate_alert_failure(
        _snapshot(state=AlertState.FIRING, consecutive_failures=4),
        error_message="invalid billing configuration",
        is_transient_error=False,
    )
    alert = BillingAlertConfiguration(state=BillingAlertConfiguration.State.FIRING, enabled=True)

    update_fields = apply_outcome(alert, outcome)

    assert outcome.notification == NotificationAction.BROKEN
    assert alert.state == BillingAlertConfiguration.State.BROKEN
    assert alert.consecutive_failures == 5
    assert alert.enabled is False
    assert "enabled" in update_fields


def test_cooldown_only_gates_repeated_firing() -> None:
    last_notified_at = NOW - timedelta(hours=1)

    initial = evaluate_alert_check(
        _snapshot(last_notified_at=last_notified_at),
        _evaluation(breached=True),
        NOW,
    )
    repeated = evaluate_alert_check(
        _snapshot(state=AlertState.FIRING, last_notified_at=last_notified_at),
        _evaluation(breached=True),
        NOW,
    )
    resolved = evaluate_alert_check(
        _snapshot(state=AlertState.FIRING, last_notified_at=last_notified_at),
        _evaluation(breached=False),
        NOW,
    )

    assert initial.notification == NotificationAction.FIRE
    assert repeated.notification == NotificationAction.NONE
    assert resolved.notification == NotificationAction.RESOLVE


def test_clear_check_resolves_and_ends_snooze() -> None:
    snooze_until = NOW + timedelta(hours=1)
    outcome = evaluate_alert_check(
        _snapshot(state=AlertState.SNOOZED, snooze_until=snooze_until),
        _evaluation(breached=False),
        NOW,
    )
    alert = BillingAlertConfiguration(
        state=BillingAlertConfiguration.State.SNOOZED,
        snooze_until=snooze_until,
    )

    apply_outcome(alert, outcome)

    assert outcome.notification == NotificationAction.RESOLVE
    assert alert.state == BillingAlertConfiguration.State.NOT_FIRING
    assert alert.snooze_until is None


def test_next_check_uses_hourly_shard_and_canonical_grid() -> None:
    alert = BillingAlertConfiguration(
        id=UUID(int=3),
        check_interval_hours=24,
        next_check_at=datetime(2026, 6, 22, 4, 17, tzinfo=UTC),
    )

    next_check_at = next_billing_alert_check_at(alert, NOW)

    assert next_check_at == datetime(2026, 6, 24, 3, 0, tzinfo=UTC)
