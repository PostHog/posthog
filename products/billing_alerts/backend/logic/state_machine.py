"""Billing adapter for the shared alert lifecycle state machine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.exceptions_capture import capture_exception

from products.alerts.backend.scheduling import compute_shard_offset_seconds
from products.billing_alerts.backend.logic.evaluator import (
    BillingAlertEvaluation,
    evaluate_billing_alert,
    expected_evaluation_date,
)
from products.billing_alerts.backend.models import (
    DAILY_CHECK_INTERVAL_HOURS,
    BillingAlertConfiguration,
    BillingAlertEvaluationClaim,
    BillingAlertEvent,
)

from common.alerting.state_machine import (
    BILLING_ALERT_POLICY,
    MAX_CONSECUTIVE_FAILURES,
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    Outcome,
    apply_disable,
    apply_enable,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    evaluate_alert_check as shared_evaluate_alert_check,
    evaluate_alert_failure as shared_evaluate_alert_failure,
)

BILLING_ALERT_SCHEDULE_INTERVAL_SECONDS = 60 * 60
EVALUATION_LEASE = timedelta(minutes=15)
EVALUATION_RETRY_BASE = timedelta(minutes=15)
EVALUATION_RETRY_MAX = timedelta(hours=6)
MAX_EVALUATION_ATTEMPTS = 8

logger = structlog.get_logger(__name__)

__all__ = [
    "BILLING_ALERT_POLICY",
    "BillingAlertAlreadyEvaluated",
    "BillingAlertCheck",
    "BillingAlertEvaluationInProgress",
    "BillingAlertConfigurationChanged",
    "MAX_CONSECUTIVE_FAILURES",
    "AlertCheckOutcome",
    "AlertState",
    "NotificationAction",
    "Outcome",
    "apply_disable",
    "apply_enable",
    "apply_outcome",
    "apply_snooze",
    "apply_threshold_change",
    "apply_unsnooze",
    "billing_alert_snapshot",
    "claim_billing_alert_evaluation",
    "lock_and_validate_billing_alert_claim",
    "commit_billing_alert_check",
    "evaluate_alert_check",
    "evaluate_alert_failure",
    "next_billing_alert_check_at",
    "prepare_billing_alert_check",
    "prepare_billing_alert_failure",
]


class BillingAlertEvaluationInProgress(Exception):
    pass


class BillingAlertConfigurationChanged(Exception):
    pass


class BillingAlertAlreadyEvaluated(Exception):
    def __init__(self, event: BillingAlertEvent | None) -> None:
        self.event = event
        super().__init__("This billing date has already been evaluated for the current configuration.")


@dataclass(frozen=True)
class BillingAlertCheck:
    alert: BillingAlertConfiguration
    claim: BillingAlertEvaluationClaim
    event: BillingAlertEvent
    outcome: AlertCheckOutcome
    snapshot: AlertSnapshot
    source: str
    is_inconclusive: bool
    now: datetime


def billing_alert_snapshot(alert: BillingAlertConfiguration) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState(alert.state),
        cooldown=timedelta(hours=alert.cooldown_hours),
        last_notified_at=alert.last_notified_at,
        snooze_until=alert.snoozed_until,
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
    state_before = AlertState(alert.state)
    alert.state = outcome.new_state.value
    alert.consecutive_failures = outcome.consecutive_failures
    update_fields = ["state", "consecutive_failures"]

    if state_before == AlertState.SNOOZED and outcome.new_state != AlertState.SNOOZED:
        alert.snoozed_until = None
        update_fields.append("snoozed_until")

    if isinstance(outcome, AlertCheckOutcome) and outcome.disable:
        alert.enabled = False
        update_fields.append("enabled")

    return update_fields


def next_billing_alert_check_at(alert: BillingAlertConfiguration, now: datetime) -> datetime:
    utc_now = now.astimezone(UTC)
    boundary_hour = alert.evaluation_delay_hours % 24
    shard_offset_seconds = compute_shard_offset_seconds(
        alert.id,
        DAILY_CHECK_INTERVAL_HOURS * 60,
        schedule_interval_seconds=BILLING_ALERT_SCHEDULE_INTERVAL_SECONDS,
    )
    next_at = utc_now.replace(hour=boundary_hour, minute=0, second=0, microsecond=0) + timedelta(
        seconds=shard_offset_seconds
    )
    return next_at + timedelta(days=1) if next_at <= utc_now else next_at


def _event_kind(outcome: AlertCheckOutcome) -> str:
    return {
        NotificationAction.NONE: BillingAlertEvent.Kind.CHECK,
        NotificationAction.FIRE: BillingAlertEvent.Kind.FIRING,
        NotificationAction.RESOLVE: BillingAlertEvent.Kind.RESOLVED,
        NotificationAction.ERROR: BillingAlertEvent.Kind.ERRORED,
        NotificationAction.BROKEN: BillingAlertEvent.Kind.BROKEN_CONFIG,
    }[outcome.notification]


def _sync_alert(target: BillingAlertConfiguration, source: BillingAlertConfiguration) -> None:
    """Copy every concrete field so callers never keep stale in-memory state after a locked read."""
    for field in BillingAlertConfiguration._meta.concrete_fields:
        setattr(target, field.attname, getattr(source, field.attname))


def claim_billing_alert_evaluation(
    alert: BillingAlertConfiguration,
    *,
    now: datetime,
) -> BillingAlertEvaluationClaim:
    lease_expires_at = now + EVALUATION_LEASE
    with transaction.atomic():
        locked_alert = BillingAlertConfiguration.objects.select_for_update().get(
            pk=alert.pk,
            organization_id=alert.organization_id,
        )
        if locked_alert.team_id is None:
            raise ValueError("Billing alert does not have an execution team.")
        if locked_alert.configuration_revision != alert.configuration_revision:
            _sync_alert(alert, locked_alert)
            raise BillingAlertConfigurationChanged("Billing alert configuration changed before evaluation began.")

        evaluation_date = locked_alert.pending_evaluation_date or expected_evaluation_date(locked_alert, now)
        try:
            claim = BillingAlertEvaluationClaim.objects.select_for_update().get(
                alert=locked_alert,
                evaluation_date=evaluation_date,
                configuration_revision=locked_alert.configuration_revision,
            )
        except BillingAlertEvaluationClaim.DoesNotExist:
            claim = BillingAlertEvaluationClaim.objects.create(
                alert=locked_alert,
                evaluation_date=evaluation_date,
                configuration_revision=locked_alert.configuration_revision,
            )

        if claim.status == BillingAlertEvaluationClaim.Status.COMPLETED:
            existing_event = claim.attempts.order_by("-attempt_number").first()
            raise BillingAlertAlreadyEvaluated(existing_event)
        if (
            claim.status == BillingAlertEvaluationClaim.Status.EVALUATING
            and claim.lease_expires_at is not None
            and claim.lease_expires_at > now
        ):
            raise BillingAlertEvaluationInProgress("A billing alert evaluation is already running.")
        if (
            claim.status == BillingAlertEvaluationClaim.Status.RETRYABLE
            and claim.next_retry_at is not None
            and claim.next_retry_at > now
        ):
            raise BillingAlertEvaluationInProgress("This billing alert evaluation is waiting to retry.")

        claim.status = BillingAlertEvaluationClaim.Status.EVALUATING
        claim.lease_expires_at = lease_expires_at
        claim.next_retry_at = None
        claim.attempt_count += 1
        claim.save(update_fields=["status", "lease_expires_at", "next_retry_at", "attempt_count", "updated_at"])

        locked_alert.pending_evaluation_date = evaluation_date
        locked_alert.retry_attempt_count = claim.attempt_count
        locked_alert.next_check_at = lease_expires_at
        locked_alert.save(
            update_fields=["pending_evaluation_date", "retry_attempt_count", "next_check_at", "updated_at"]
        )
        _sync_alert(alert, locked_alert)
        return claim


def _new_event(
    alert: BillingAlertConfiguration,
    claim: BillingAlertEvaluationClaim,
    *,
    source: str,
    kind: str,
    state_after: str,
) -> BillingAlertEvent:
    if alert.team_id is None:
        raise ValueError("Billing alert does not have an execution team.")
    return BillingAlertEvent(
        claim=claim,
        team_id=alert.team_id,
        kind=kind,
        source=source,
        attempt_number=claim.attempt_count,
        metric=alert.metric,
        state_before=alert.state,
        state_after=state_after,
    )


def _prepare_billing_alert_failure(
    alert: BillingAlertConfiguration,
    claim: BillingAlertEvaluationClaim,
    error: Exception,
    *,
    source: str,
    now: datetime,
    query_duration_ms: int | None,
    is_transient_error: bool,
    reason: str,
) -> BillingAlertCheck:
    snapshot = billing_alert_snapshot(alert)
    outcome = evaluate_alert_failure(
        snapshot,
        error_message=reason,
        is_transient_error=is_transient_error,
    )
    event = _new_event(
        alert,
        claim,
        source=source,
        kind=_event_kind(outcome),
        state_after=outcome.new_state.value,
    )
    event.threshold_breached = False
    event.query_duration_ms = query_duration_ms
    event.error_code = error.__class__.__name__
    event.error_message = reason
    event.is_transient_error = is_transient_error
    event.reason = reason
    event.payload = {}
    return BillingAlertCheck(
        alert=alert,
        claim=claim,
        event=event,
        outcome=outcome,
        snapshot=snapshot,
        source=source,
        is_inconclusive=False,
        now=now,
    )


def prepare_billing_alert_failure(
    alert: BillingAlertConfiguration,
    error: Exception,
    *,
    source: str,
    now: datetime | None = None,
    query_duration_ms: int | None = None,
    is_transient_error: bool = False,
    reason: str = "Billing alert evaluation failed.",
) -> BillingAlertCheck:
    now = now or timezone.now()
    claim = claim_billing_alert_evaluation(alert, now=now)
    return _prepare_billing_alert_failure(
        alert,
        claim,
        error,
        source=source,
        now=now,
        query_duration_ms=query_duration_ms,
        is_transient_error=is_transient_error,
        reason=reason,
    )


def _prepare_billing_alert_evaluation(
    alert: BillingAlertConfiguration,
    claim: BillingAlertEvaluationClaim,
    evaluation: BillingAlertEvaluation,
    *,
    source: str,
    now: datetime,
) -> BillingAlertCheck:
    snapshot = billing_alert_snapshot(alert)
    outcome = evaluate_alert_check(snapshot, evaluation, now)
    event = _new_event(
        alert,
        claim,
        source=source,
        kind=_event_kind(outcome),
        state_after=outcome.new_state.value,
    )
    event.period_start = evaluation.period_start
    event.period_end = evaluation.period_end
    event.current_value = evaluation.current_value
    event.baseline_value = evaluation.baseline_value
    event.absolute_delta = evaluation.absolute_delta
    event.relative_delta_percentage = evaluation.relative_delta_percentage
    event.threshold_value_snapshot = alert.threshold_value
    event.threshold_percentage_snapshot = alert.threshold_percentage
    event.minimum_value_snapshot = alert.minimum_value
    event.threshold_breached = evaluation.threshold_breached
    event.query_duration_ms = evaluation.query_duration_ms
    event.reason = evaluation.reason
    event.payload = evaluation.payload
    return BillingAlertCheck(
        alert=alert,
        claim=claim,
        event=event,
        outcome=outcome,
        snapshot=snapshot,
        source=source,
        is_inconclusive=evaluation.is_inconclusive,
        now=now,
    )


def prepare_billing_alert_check(
    alert: BillingAlertConfiguration,
    *,
    source: str,
    now: datetime | None = None,
    billing_response: dict | None = None,
    query_duration_ms: int | None = None,
) -> BillingAlertCheck:
    now = now or timezone.now()
    claim = claim_billing_alert_evaluation(alert, now=now)
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
        return _prepare_billing_alert_failure(
            alert,
            claim,
            error,
            source=source,
            now=now,
            query_duration_ms=query_duration_ms,
            is_transient_error=False,
            reason="Billing alert evaluation failed.",
        )

    return _prepare_billing_alert_evaluation(alert, claim, evaluation, source=source, now=now)


def _retry_at(claim: BillingAlertEvaluationClaim, now: datetime) -> datetime:
    multiplier = 2 ** max(claim.attempt_count - 1, 0)
    delay = min(EVALUATION_RETRY_BASE * multiplier, EVALUATION_RETRY_MAX)
    return now + delay


def _validate_claim(
    check: BillingAlertCheck, alert: BillingAlertConfiguration, claim: BillingAlertEvaluationClaim
) -> None:
    if alert.configuration_revision != claim.configuration_revision:
        raise BillingAlertConfigurationChanged("Billing alert configuration changed during evaluation.")
    if (
        claim.status != BillingAlertEvaluationClaim.Status.EVALUATING
        or claim.attempt_count != check.event.attempt_number
    ):
        raise BillingAlertEvaluationInProgress("A newer billing alert evaluation owns this claim.")


def lock_and_validate_billing_alert_claim(check: BillingAlertCheck) -> None:
    """Take the alert and claim locks used by configuration updates; they persist for the rest of
    the caller's transaction, fencing notification delivery against concurrent config changes."""
    locked_alert = BillingAlertConfiguration.objects.select_for_update().get(
        pk=check.alert.pk,
        organization_id=check.alert.organization_id,
    )
    claim = BillingAlertEvaluationClaim.objects.select_for_update().get(
        pk=check.claim.pk,
        alert_id=check.alert.pk,
    )
    _validate_claim(check, locked_alert, claim)


def commit_billing_alert_check(
    check: BillingAlertCheck,
    *,
    notification_delivered: bool,
    destination_ids: list[str] | None = None,
) -> BillingAlertEvent:
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

    retry_requested = (
        check.is_inconclusive
        or check.event.is_transient_error
        or (notification_requested and not notification_delivered)
    )

    with transaction.atomic():
        locked_alert = BillingAlertConfiguration.objects.select_for_update().get(
            pk=check.alert.pk,
            organization_id=check.alert.organization_id,
        )
        claim = BillingAlertEvaluationClaim.objects.select_for_update().get(
            pk=check.claim.pk,
            alert_id=check.alert.pk,
        )
        _validate_claim(check, locked_alert, claim)
        event = check.event
        event.claim = claim
        event.team_id = locked_alert.team_id or event.team_id

        event.state_after = committed_outcome.new_state.value
        if notification_requested and notification_delivered:
            event.notification_sent_at = check.now
            event.targets_notified = {"hog_functions": destination_ids or []}

        update_fields = apply_outcome(locked_alert, committed_outcome)
        locked_alert.last_checked_at = check.now
        update_fields.append("last_checked_at")

        should_retry = retry_requested and claim.attempt_count < MAX_EVALUATION_ATTEMPTS and locked_alert.enabled
        if should_retry:
            retry_at = _retry_at(claim, check.now)
            locked_alert.next_check_at = retry_at
            locked_alert.pending_evaluation_date = claim.evaluation_date
            locked_alert.retry_attempt_count = claim.attempt_count
            claim.status = BillingAlertEvaluationClaim.Status.RETRYABLE
            claim.next_retry_at = retry_at
        else:
            locked_alert.next_check_at = next_billing_alert_check_at(locked_alert, check.now)
            locked_alert.pending_evaluation_date = None
            locked_alert.retry_attempt_count = 0
            claim.status = BillingAlertEvaluationClaim.Status.COMPLETED
            claim.next_retry_at = None
        update_fields.extend(["next_check_at", "pending_evaluation_date", "retry_attempt_count"])

        if notification_requested and notification_delivered and check.outcome.update_last_notified_at:
            locked_alert.last_notified_at = check.now
            update_fields.append("last_notified_at")

        locked_alert.save(update_fields=[*set(update_fields), "updated_at"])
        event.save(force_insert=True)
        claim.lease_expires_at = None
        claim.save(update_fields=["status", "lease_expires_at", "next_retry_at", "updated_at"])
        _sync_alert(check.alert, locked_alert)
        return event
