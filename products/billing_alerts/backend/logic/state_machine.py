from __future__ import annotations

from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception

from products.billing_alerts.backend.logic.evaluator import BillingAlertEvaluation, evaluate_billing_alert
from products.billing_alerts.backend.models import (
    MAX_FAILURES_BEFORE_BROKEN,
    BillingAlertConfiguration,
    BillingAlertEvent,
)

logger = structlog.get_logger(__name__)


def _cooldown_suppresses(alert: BillingAlertConfiguration, now: datetime) -> bool:
    if alert.last_notified_at is None or alert.cooldown_hours <= 0:
        return False
    return alert.last_notified_at + timedelta(hours=alert.cooldown_hours) > now


def _snooze_suppresses(alert: BillingAlertConfiguration, now: datetime) -> bool:
    return bool(alert.snooze_until and alert.snooze_until > now)


def _state_after(alert: BillingAlertConfiguration, evaluation: BillingAlertEvaluation, now: datetime) -> str:
    if evaluation.is_inconclusive:
        return alert.state
    if evaluation.threshold_breached and _snooze_suppresses(alert, now):
        return BillingAlertConfiguration.State.SNOOZED
    if evaluation.threshold_breached:
        return BillingAlertConfiguration.State.FIRING
    return BillingAlertConfiguration.State.NOT_FIRING


def _event_kind(
    alert: BillingAlertConfiguration,
    evaluation: BillingAlertEvaluation,
    next_state: str,
    now: datetime,
) -> str:
    if evaluation.is_inconclusive:
        return BillingAlertEvent.Kind.CHECK
    if evaluation.threshold_breached:
        if next_state == alert.State.SNOOZED:
            return BillingAlertEvent.Kind.CHECK
        if alert.state == alert.State.FIRING and _cooldown_suppresses(alert, now):
            return BillingAlertEvent.Kind.CHECK
        return BillingAlertEvent.Kind.FIRING
    if (
        alert.state
        in (
            BillingAlertConfiguration.State.FIRING,
            BillingAlertConfiguration.State.SNOOZED,
        )
        and not evaluation.threshold_breached
    ):
        return BillingAlertEvent.Kind.RESOLVED
    return BillingAlertEvent.Kind.CHECK


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
        locked_alert = BillingAlertConfiguration.objects.unscoped().select_for_update().get(pk=alert.pk)
        state_before = locked_alert.state
        locked_alert.consecutive_failures += 1
        next_state = (
            BillingAlertConfiguration.State.BROKEN
            if locked_alert.consecutive_failures >= MAX_FAILURES_BEFORE_BROKEN
            else BillingAlertConfiguration.State.ERRORED
        )
        event_kind = (
            BillingAlertEvent.Kind.BROKEN_CONFIG
            if next_state == BillingAlertConfiguration.State.BROKEN
            else BillingAlertEvent.Kind.ERRORED
        )
        locked_alert.state = next_state
        locked_alert.last_checked_at = now
        locked_alert.next_check_at = now + timedelta(hours=locked_alert.check_interval_hours)
        if next_state == BillingAlertConfiguration.State.BROKEN:
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
        return BillingAlertEvent.objects.unscoped().create(
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
    state_before = alert.state

    try:
        evaluation = evaluate_billing_alert(
            alert,
            now=now,
            billing_response=billing_response,
            query_duration_ms=query_duration_ms,
        )
        next_state = _state_after(alert, evaluation, now)
        event_kind = _event_kind(alert, evaluation, next_state, now)

        with transaction.atomic():
            event_defaults = {
                "period_start": evaluation.period_start,
                "period_end": evaluation.period_end,
                "metric": alert.metric,
                "current_value": evaluation.current_value,
                "baseline_value": evaluation.baseline_value,
                "absolute_delta": evaluation.absolute_delta,
                "relative_delta_percentage": evaluation.relative_delta_percentage,
                "threshold_value_snapshot": alert.threshold_value,
                "threshold_percentage_snapshot": alert.threshold_percentage,
                "minimum_value_snapshot": alert.minimum_value,
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
                event, _ = BillingAlertEvent.objects.unscoped().update_or_create(
                    alert=alert,
                    kind=event_kind,
                    evaluation_date=evaluation.evaluation_date,
                    defaults={**event_defaults, "team_id": alert.team_id},
                )
            else:
                event = BillingAlertEvent.objects.unscoped().create(
                    alert=alert,
                    team_id=alert.team_id,
                    kind=event_kind,
                    evaluation_date=evaluation.evaluation_date,
                    **event_defaults,
                )
            alert.state = next_state
            alert.last_checked_at = now
            alert.next_check_at = now + timedelta(hours=alert.check_interval_hours)
            alert.consecutive_failures = 0
            alert.save(
                update_fields=[
                    "state",
                    "last_checked_at",
                    "next_check_at",
                    "consecutive_failures",
                    "updated_at",
                ]
            )
            return event
    except Exception as e:
        capture_exception(e, {"alert_id": str(alert.id), "feature": "billing_alerts"})
        logger.exception("Billing alert evaluation failed", alert_id=str(alert.id))
        return record_billing_alert_failure(alert, e, now=now)
