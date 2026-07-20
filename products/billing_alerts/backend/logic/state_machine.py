"""Billing adapter for the shared alert lifecycle state machine.

Billing owns evaluation, persistence, and audit events. Lifecycle decisions come
from ``common.alerting.state_machine`` and every write to ``state`` or
``consecutive_failures`` goes through ``apply_outcome`` below.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception

from products.alerts.backend.scheduling import advance_next_check_at, compute_shard_offset_seconds
from products.billing_alerts.backend.logic.evaluator import BillingAlertEvaluation, evaluate_billing_alert
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent

from common.alerting.state_machine import (
    MAX_CONSECUTIVE_FAILURES,
    AlertCheckOutcome,
    AlertPolicy,
    AlertSnapshot,
    AlertState,
    CheckInput,
    ControlPlaneOutcome,
    InvalidTransition,
    NotificationAction,
    Outcome,
    apply_disable,
    apply_enable,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    apply_user_reset,
    evaluate_alert_check as shared_evaluate_alert_check,
    evaluate_alert_failure as shared_evaluate_alert_failure,
)

BILLING_ALERT_POLICY = AlertPolicy(
    broken_is_terminal=False,
    transient_errors_count_toward_broken=True,
    notify_error_on_every_failure=True,
    cooldown_gates_initial_fire=False,
    cooldown_gates_resolve=False,
    renotify_while_firing=True,
    clear_check_ends_snooze=True,
    disable_when_broken=True,
)

BILLING_ALERT_SCHEDULE_INTERVAL_SECONDS = 60 * 60

logger = structlog.get_logger(__name__)

__all__ = [
    "BILLING_ALERT_POLICY",
    "BillingAlertCheck",
    "MAX_CONSECUTIVE_FAILURES",
    "AlertCheckOutcome",
    "AlertState",
    "ControlPlaneOutcome",
    "InvalidTransition",
    "NotificationAction",
    "Outcome",
    "apply_disable",
    "apply_enable",
    "apply_outcome",
    "apply_snooze",
    "apply_threshold_change",
    "apply_unsnooze",
    "apply_user_reset",
    "billing_alert_snapshot",
    "commit_billing_alert_check",
    "evaluate_alert_check",
    "evaluate_alert_failure",
    "event_should_dispatch",
    "next_billing_alert_check_at",
    "prepare_billing_alert_check",
    "prepare_billing_alert_failure",
]


@dataclass(frozen=True)
class BillingAlertCheck:
    """A billing evaluation and proposed shared lifecycle outcome, before delivery or persistence."""

    alert: BillingAlertConfiguration
    event: BillingAlertEvent
    outcome: AlertCheckOutcome
    snapshot: AlertSnapshot
    configuration_updated_at: datetime | None
    now: datetime


def billing_alert_snapshot(alert: BillingAlertConfiguration) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(alert.state),
        cooldown=timedelta(hours=alert.cooldown_hours),
        last_notified_at=alert.last_notified_at,
        snooze_until=alert.snooze_until,
        consecutive_failures=alert.consecutive_failures,
    )


def evaluate_alert_check(
    snapshot: AlertSnapshot,
    evaluation: BillingAlertEvaluation,
    now: datetime,
) -> AlertCheckOutcome:
    return shared_evaluate_alert_check(
        snapshot,
        CheckInput(
            threshold_breached=evaluation.threshold_breached,
            is_inconclusive=evaluation.is_inconclusive,
        ),
        now,
        policy=BILLING_ALERT_POLICY,
    )


def evaluate_alert_failure(
    snapshot: AlertSnapshot,
    *,
    error_message: str,
    is_transient_error: bool,
) -> AlertCheckOutcome:
    return shared_evaluate_alert_failure(
        snapshot,
        error_message=error_message,
        is_transient_error=is_transient_error,
        policy=BILLING_ALERT_POLICY,
    )


def apply_outcome(alert: BillingAlertConfiguration, outcome: Outcome) -> list[str]:
    """Apply a shared outcome to the billing model.

    This is the only legal mutator of billing lifecycle state and failure count.
    Callers own saving the returned fields with their other atomic writes.
    """
    state_before = AlertState(alert.state)
    alert.state = outcome.new_state.value
    alert.consecutive_failures = outcome.consecutive_failures
    update_fields = ["state", "consecutive_failures"]

    if state_before == AlertState.SNOOZED and outcome.new_state != AlertState.SNOOZED:
        alert.snooze_until = None
        update_fields.append("snooze_until")

    if isinstance(outcome, AlertCheckOutcome) and outcome.disable:
        alert.enabled = False
        update_fields.append("enabled")

    return update_fields


def next_billing_alert_check_at(alert: BillingAlertConfiguration, now: datetime) -> datetime:
    check_interval_minutes = alert.check_interval_hours * 60
    shard_offset_seconds = compute_shard_offset_seconds(
        alert.id,
        check_interval_minutes,
        schedule_interval_seconds=BILLING_ALERT_SCHEDULE_INTERVAL_SECONDS,
    )
    return advance_next_check_at(
        alert.next_check_at,
        check_interval_minutes,
        now,
        shard_offset_seconds=shard_offset_seconds,
    )


def _event_kind(outcome: AlertCheckOutcome) -> str:
    return {
        NotificationAction.NONE: BillingAlertEvent.Kind.CHECK,
        NotificationAction.FIRE: BillingAlertEvent.Kind.FIRING,
        NotificationAction.RESOLVE: BillingAlertEvent.Kind.RESOLVED,
        NotificationAction.ERROR: BillingAlertEvent.Kind.ERRORED,
        NotificationAction.BROKEN: BillingAlertEvent.Kind.BROKEN_CONFIG,
    }[outcome.notification]


def event_should_dispatch(event: BillingAlertEvent) -> bool:
    return event.kind in {
        BillingAlertEvent.Kind.FIRING,
        BillingAlertEvent.Kind.RESOLVED,
        BillingAlertEvent.Kind.ERRORED,
        BillingAlertEvent.Kind.BROKEN_CONFIG,
    }


def _save_outcome(
    alert: BillingAlertConfiguration,
    outcome: AlertCheckOutcome,
    *,
    now: datetime,
) -> None:
    update_fields = apply_outcome(alert, outcome)
    alert.last_checked_at = now
    alert.next_check_at = next_billing_alert_check_at(alert, now)
    alert.save(update_fields=[*update_fields, "last_checked_at", "next_check_at", "updated_at"])


def _sync_alert(target: BillingAlertConfiguration, source: BillingAlertConfiguration) -> None:
    target.enabled = source.enabled
    target.state = source.state
    target.snooze_until = source.snooze_until
    target.last_checked_at = source.last_checked_at
    target.next_check_at = source.next_check_at
    target.last_notified_at = source.last_notified_at
    target.consecutive_failures = source.consecutive_failures
    target.updated_at = source.updated_at


def _refresh_lifecycle_snapshot(alert: BillingAlertConfiguration) -> None:
    """Refresh fields that can change while a scheduler or API caller holds a stale model instance."""
    current = BillingAlertConfiguration.objects.only(
        "enabled",
        "state",
        "snooze_until",
        "last_checked_at",
        "next_check_at",
        "last_notified_at",
        "consecutive_failures",
        "updated_at",
    ).get(pk=alert.pk)
    _sync_alert(alert, current)


def prepare_billing_alert_failure(
    alert: BillingAlertConfiguration,
    error: Exception,
    *,
    now: datetime | None = None,
    query_duration_ms: int | None = None,
    is_transient_error: bool = False,
    reason: str = "Billing alert evaluation failed.",
) -> BillingAlertCheck:
    now = now or timezone.now()
    _refresh_lifecycle_snapshot(alert)
    snapshot = billing_alert_snapshot(alert)
    outcome = evaluate_alert_failure(
        snapshot,
        error_message=str(error),
        is_transient_error=is_transient_error,
    )
    event = BillingAlertEvent(
        alert=alert,
        team_id=alert.team_id,
        kind=_event_kind(outcome),
        evaluation_date=None,
        period_start=None,
        period_end=None,
        metric=alert.metric,
        threshold_breached=False,
        state_before=alert.state,
        state_after=outcome.new_state.value,
        query_duration_ms=query_duration_ms,
        error_code=error.__class__.__name__,
        error_message=str(error),
        is_transient_error=is_transient_error,
        reason=reason,
        payload={},
    )
    return BillingAlertCheck(
        alert=alert,
        event=event,
        outcome=outcome,
        snapshot=snapshot,
        configuration_updated_at=alert.updated_at,
        now=now,
    )


def _prepare_billing_alert_evaluation(
    alert: BillingAlertConfiguration,
    evaluation: BillingAlertEvaluation,
    *,
    now: datetime,
) -> BillingAlertCheck:
    snapshot = billing_alert_snapshot(alert)
    outcome = evaluate_alert_check(snapshot, evaluation, now)
    event = BillingAlertEvent(
        alert=alert,
        team_id=alert.team_id,
        kind=_event_kind(outcome),
        evaluation_date=evaluation.evaluation_date,
        period_start=evaluation.period_start,
        period_end=evaluation.period_end,
        metric=alert.metric,
        current_value=evaluation.current_value,
        baseline_value=evaluation.baseline_value,
        absolute_delta=evaluation.absolute_delta,
        relative_delta_percentage=evaluation.relative_delta_percentage,
        threshold_value_snapshot=alert.threshold_value,
        threshold_percentage_snapshot=alert.threshold_percentage,
        minimum_value_snapshot=alert.minimum_value,
        threshold_breached=evaluation.threshold_breached,
        state_before=alert.state,
        state_after=outcome.new_state.value,
        query_duration_ms=evaluation.query_duration_ms,
        error_code=None,
        error_message=None,
        is_transient_error=False,
        reason=evaluation.reason,
        payload=evaluation.payload,
    )
    return BillingAlertCheck(
        alert=alert,
        event=event,
        outcome=outcome,
        snapshot=snapshot,
        configuration_updated_at=alert.updated_at,
        now=now,
    )


def _persist_event(event: BillingAlertEvent) -> BillingAlertEvent:
    if event.kind != BillingAlertEvent.Kind.CHECK:
        event.save(force_insert=True)
        return event

    persisted, _ = BillingAlertEvent.objects.update_or_create(
        alert=event.alert,
        kind=event.kind,
        evaluation_date=event.evaluation_date,
        defaults={
            "team_id": event.team_id,
            "period_start": event.period_start,
            "period_end": event.period_end,
            "metric": event.metric,
            "current_value": event.current_value,
            "baseline_value": event.baseline_value,
            "absolute_delta": event.absolute_delta,
            "relative_delta_percentage": event.relative_delta_percentage,
            "threshold_value_snapshot": event.threshold_value_snapshot,
            "threshold_percentage_snapshot": event.threshold_percentage_snapshot,
            "minimum_value_snapshot": event.minimum_value_snapshot,
            "threshold_breached": event.threshold_breached,
            "state_before": event.state_before,
            "state_after": event.state_after,
            "notification_sent_at": event.notification_sent_at,
            "targets_notified": event.targets_notified,
            "query_duration_ms": event.query_duration_ms,
            "error_code": event.error_code,
            "error_message": event.error_message,
            "is_transient_error": event.is_transient_error,
            "reason": event.reason,
            "payload": event.payload,
        },
    )
    return persisted


def prepare_billing_alert_check(
    alert: BillingAlertConfiguration,
    *,
    now: datetime | None = None,
    billing_response: dict | None = None,
    query_duration_ms: int | None = None,
) -> BillingAlertCheck:
    now = now or timezone.now()
    _refresh_lifecycle_snapshot(alert)
    try:
        evaluation = evaluate_billing_alert(
            alert,
            now=now,
            billing_response=billing_response,
            query_duration_ms=query_duration_ms,
        )
    except Exception as error:
        capture_exception(error, {"alert_id": str(alert.id), "feature": "billing_alerts"})
        logger.exception("Billing alert evaluation failed", alert_id=str(alert.id))
        return prepare_billing_alert_failure(alert, error, now=now)

    return _prepare_billing_alert_evaluation(alert, evaluation, now=now)


def commit_billing_alert_check(
    check: BillingAlertCheck,
    *,
    notification_delivered: bool,
    destination_ids: list[str] | None = None,
) -> BillingAlertEvent:
    """Persist a check after the shared delivery barrier has resolved.

    Failed notification delivery preserves the prior successful lifecycle state
    and failure counter so the next scheduled check can retry the transition.
    """
    notification_requested = check.outcome.notification != NotificationAction.NONE
    committed_outcome = check.outcome
    if notification_requested and not notification_delivered:
        committed_outcome = replace(
            check.outcome,
            new_state=check.snapshot.state,
            consecutive_failures=min(check.snapshot.consecutive_failures, check.outcome.consecutive_failures),
            update_last_notified_at=False,
            disable=False,
        )

    with transaction.atomic():
        locked_alert = BillingAlertConfiguration.objects.select_for_update().get(pk=check.alert.pk)
        event = check.event
        event.alert = locked_alert
        event.team_id = locked_alert.team_id

        if locked_alert.updated_at != check.configuration_updated_at:
            # A control-plane edit won the race while evaluation or delivery was in flight.
            # Keep its lifecycle state and scheduling intact; a later check will evaluate the new configuration.
            event.state_after = locked_alert.state
            if notification_requested and notification_delivered:
                event.notification_sent_at = check.now
                event.targets_notified = {"hog_functions": destination_ids or []}
            persisted_event = _persist_event(event)
            _sync_alert(check.alert, locked_alert)
            return persisted_event

        event.state_after = committed_outcome.new_state.value
        if notification_requested and notification_delivered:
            event.notification_sent_at = check.now
            event.targets_notified = {"hog_functions": destination_ids or []}

        _save_outcome(locked_alert, committed_outcome, now=check.now)
        if notification_requested and notification_delivered and check.outcome.update_last_notified_at:
            locked_alert.last_notified_at = check.now
            locked_alert.save(update_fields=["last_notified_at", "updated_at"])
        persisted_event = _persist_event(event)
        _sync_alert(check.alert, locked_alert)
        return persisted_event
