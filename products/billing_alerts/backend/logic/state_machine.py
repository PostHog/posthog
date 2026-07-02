from __future__ import annotations

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception

from products.billing_alerts.backend.logic.evaluator import BillingAlertEvaluation, evaluate_billing_alert
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent

from common.alerting.state_machine import (
    BILLING_ALERT_POLICY,
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    evaluate_alert_check,
    evaluate_alert_failure,
)

logger = structlog.get_logger(__name__)

_NOTIFICATION_EVENT_KINDS: dict[NotificationAction, str] = {
    NotificationAction.NONE: BillingAlertEvent.Kind.CHECK,
    NotificationAction.FIRE: BillingAlertEvent.Kind.FIRING,
    NotificationAction.RESOLVE: BillingAlertEvent.Kind.RESOLVED,
    NotificationAction.ERROR: BillingAlertEvent.Kind.ERRORED,
    NotificationAction.BROKEN: BillingAlertEvent.Kind.BROKEN_CONFIG,
}


def _to_snapshot(alert: BillingAlertConfiguration) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(alert.state),
        cooldown=timedelta(hours=alert.cooldown_hours),
        last_notified_at=alert.last_notified_at,
        snooze_until=alert.snooze_until,
        consecutive_failures=alert.consecutive_failures,
    )


def _decide(
    alert: BillingAlertConfiguration,
    evaluation: BillingAlertEvaluation,
    now: datetime,
) -> AlertCheckOutcome:
    return evaluate_alert_check(
        _to_snapshot(alert),
        CheckInput(
            threshold_breached=evaluation.threshold_breached,
            is_inconclusive=evaluation.is_inconclusive,
        ),
        now,
        policy=BILLING_ALERT_POLICY,
    )


def event_should_dispatch(event: BillingAlertEvent) -> bool:
    return event.kind in {
        BillingAlertEvent.Kind.FIRING,
        BillingAlertEvent.Kind.RESOLVED,
        BillingAlertEvent.Kind.ERRORED,
        BillingAlertEvent.Kind.BROKEN_CONFIG,
    }


def record_billing_alert_failure(
    alert: BillingAlertConfiguration,
    error: Exception,
    *,
    now: datetime | None = None,
    query_duration_ms: int | None = None,
    is_transient_error: bool = False,
    reason: str = "Billing alert evaluation failed.",
) -> BillingAlertEvent:
    now = now or timezone.now()
    with transaction.atomic():
        locked_alert = BillingAlertConfiguration.objects.select_for_update().get(pk=alert.pk)
        state_before = locked_alert.state
        outcome = evaluate_alert_failure(
            _to_snapshot(locked_alert),
            error_message=str(error),
            is_transient_error=is_transient_error,
            policy=BILLING_ALERT_POLICY,
        )
        next_state = outcome.new_state.value
        event_kind = _NOTIFICATION_EVENT_KINDS[outcome.notification]
        locked_alert.state = next_state
        locked_alert.consecutive_failures = outcome.consecutive_failures
        locked_alert.last_checked_at = now
        locked_alert.next_check_at = now + timedelta(hours=locked_alert.check_interval_hours)
        if outcome.disable:
            locked_alert.enabled = False
        locked_alert.save(
            update_fields=[
                "enabled",
                "state",
                "last_checked_at",
                "next_check_at",
                "consecutive_failures",
                "updated_at",
            ]
        )
        return BillingAlertEvent.objects.create(
            alert=locked_alert,
            team_id=locked_alert.team_id,
            kind=event_kind,
            evaluation_date=None,
            period_start=None,
            period_end=None,
            metric=locked_alert.metric,
            threshold_breached=False,
            state_before=state_before,
            state_after=next_state,
            query_duration_ms=query_duration_ms,
            error_code=error.__class__.__name__,
            error_message=str(error),
            is_transient_error=is_transient_error,
            reason=reason,
            payload={},
        )


def evaluate_and_record_billing_alert(
    alert: BillingAlertConfiguration,
    *,
    now: datetime | None = None,
    billing_response: dict | None = None,
    query_duration_ms: int | None = None,
) -> BillingAlertEvent:
    now = now or timezone.now()

    try:
        evaluation = evaluate_billing_alert(
            alert,
            now=now,
            billing_response=billing_response,
            query_duration_ms=query_duration_ms,
        )

        with transaction.atomic():
            locked_alert = BillingAlertConfiguration.objects.select_for_update().get(pk=alert.pk)
            state_before = locked_alert.state
            outcome = _decide(locked_alert, evaluation, now)
            next_state = outcome.new_state.value
            event_kind = _NOTIFICATION_EVENT_KINDS[outcome.notification]
            event_defaults = {
                "period_start": evaluation.period_start,
                "period_end": evaluation.period_end,
                "metric": locked_alert.metric,
                "current_value": evaluation.current_value,
                "baseline_value": evaluation.baseline_value,
                "absolute_delta": evaluation.absolute_delta,
                "relative_delta_percentage": evaluation.relative_delta_percentage,
                "threshold_value_snapshot": locked_alert.threshold_value,
                "threshold_percentage_snapshot": locked_alert.threshold_percentage,
                "minimum_value_snapshot": locked_alert.minimum_value,
                "threshold_breached": evaluation.threshold_breached,
                "state_before": state_before,
                "state_after": next_state,
                "query_duration_ms": evaluation.query_duration_ms,
                "error_code": None,
                "error_message": None,
                "is_transient_error": False,
                "reason": evaluation.reason,
                "payload": evaluation.payload,
            }
            if event_kind == BillingAlertEvent.Kind.CHECK:
                event, _ = BillingAlertEvent.objects.update_or_create(
                    alert=locked_alert,
                    kind=event_kind,
                    evaluation_date=evaluation.evaluation_date,
                    defaults={**event_defaults, "team_id": locked_alert.team_id},
                )
            else:
                event = BillingAlertEvent.objects.create(
                    alert=locked_alert,
                    team_id=locked_alert.team_id,
                    kind=event_kind,
                    evaluation_date=evaluation.evaluation_date,
                    **event_defaults,
                )
            locked_alert.state = next_state
            locked_alert.last_checked_at = now
            locked_alert.next_check_at = now + timedelta(hours=locked_alert.check_interval_hours)
            locked_alert.consecutive_failures = outcome.consecutive_failures
            # outcome.update_last_notified_at is deliberately not consumed: billing's
            # cooldown clock starts when a notification actually sends, so the dispatch
            # path in notifications.py owns last_notified_at (and rolls it back on
            # send failure).
            locked_alert.save(
                update_fields=[
                    "state",
                    "last_checked_at",
                    "next_check_at",
                    "consecutive_failures",
                    "updated_at",
                ]
            )
            alert.state = locked_alert.state
            alert.last_checked_at = locked_alert.last_checked_at
            alert.next_check_at = locked_alert.next_check_at
            alert.consecutive_failures = locked_alert.consecutive_failures
            return event
    except Exception as e:
        capture_exception(e, {"alert_id": str(alert.id), "feature": "billing_alerts"})
        logger.exception("Billing alert evaluation failed", alert_id=str(alert.id))
        return record_billing_alert_failure(alert, e, now=now)
