"""Evaluation of due billing alerts on the shared alerts platform.

Each check reads the organization's running spend total for the current billing period and
compares it with the alert's threshold. The platform's default lifecycle decides what the result
means, and the platform's interval schedule decides when the next check runs. A failed check needs
no retry of its own, because the next check reads the same running total.

Billing's own stack still evaluates the same alerts and is the only stack that notifies anyone.
This decides what the platform would have said and delivers nothing.

Each platform row resolves to its billing alert through `legacy_configuration_id`, because the
metric, the threshold, `enabled` and the snooze are edited on that row.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db.models import F

import structlog

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import due_checks, slot_of
from products.alerts_platform.backend.facade.contracts import (
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SkipReason,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.lifecycle import (
    NOTIFICATION_EVENT_KINDS,
    PLATFORM_DEFAULT_ALERT_POLICY,
    AlertSnapshot,
    AlertState,
    CheckInput,
    ControlPlaneOutcome,
    NotificationAction,
    Outcome,
    decide_firing_episode,
    evaluate_alert_check,
)
from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES, payload_bytes
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_deferred,
    increment_checks_skipped,
    increment_state_transition,
    record_scheduler_lag,
    safe_record,
)
from products.billing_alerts.backend.logic.evaluator import (
    BillingAlertEvaluationError,
    current_period_amount,
    fetch_billing_data,
)
from products.billing_alerts.backend.models import BillingAlertConfiguration

logger = structlog.get_logger(__name__)

SOURCE = SourceKind.BILLING.value

FETCH_FAILED = "Billing alert data fetch failed."


@frozen
class _BillingStatus:
    """One organization's billing status, fetched once per batch, or None when the call failed."""

    response: dict[str, Any] | None
    duration_ms: int | None = None


def evaluate_billing_batch(team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    """Decides every due billing check in one batch key. Writes nothing."""
    checks = due_checks(team_id, SOURCE, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    legacy_ids = [check.legacy_configuration_id for check in checks if check.legacy_configuration_id is not None]
    # Scoped to the batch's team and its organization, so a copy can only read an alert it belongs to.
    alerts = {
        alert.id: alert
        for alert in BillingAlertConfiguration.objects.filter(
            id__in=legacy_ids, team_id=team_id, organization_id=F("team__organization_id")
        ).select_related("organization")
    }
    statuses: dict[UUID, _BillingStatus] = {}

    # Read before any billing call, so the fetches do not count as scheduler lag.
    started_at = datetime.now(UTC)
    for check in checks:
        if check.next_check_at is not None:
            lag_ms = int((started_at - check.next_check_at).total_seconds() * 1000)
            if lag_ms > 0:
                safe_record(record_scheduler_lag, SOURCE, lag_ms)

    outcomes = tuple(
        _decide(
            check,
            alerts.get(check.legacy_configuration_id) if check.legacy_configuration_id else None,
            cutoff,
            statuses,
        )
        for check in checks
    )
    return _within_payload_bound(outcomes, team_id)


def _within_payload_bound(outcomes: tuple[PlatformAlertOutcome, ...], team_id: int) -> SourceBatchEvaluation:
    """The outcomes that fit the platform's batch payload bound. A check left out keeps its due time,
    so a later tick evaluates it again. Billing fetches once per organization, so evaluating the
    whole batch before trimming costs no extra billing call."""
    kept: list[PlatformAlertOutcome] = []
    spent = 0
    for outcome in outcomes:
        size = payload_bytes(outcome)
        if size > MAX_BATCH_PAYLOAD_BYTES:
            # It never fits, so it would stay due forever without anyone seeing why.
            logger.error(
                "Billing alert outcome exceeds the whole batch payload budget",
                team_id=team_id,
                configuration_id=str(outcome.configuration_id),
                size_bytes=size,
                budget_bytes=MAX_BATCH_PAYLOAD_BYTES,
            )
        if spent + size > MAX_BATCH_PAYLOAD_BYTES:
            # Skip rather than stop, so one oversized outcome cannot hold back every check after it.
            continue
        spent += size
        kept.append(outcome)
    deferred = len(outcomes) - len(kept)
    if deferred:
        logger.warning(
            "Deferred billing alert checks over the batch payload byte budget",
            team_id=team_id,
            recorded=len(kept),
            deferred=deferred,
            budget_bytes=MAX_BATCH_PAYLOAD_BYTES,
        )
        safe_record(increment_checks_deferred, SOURCE, deferred)
    return SourceBatchEvaluation(outcomes=tuple(kept), deliveries=(), omitted=deferred)


def _decide(
    check: PlatformAlertCheckInput,
    alert: BillingAlertConfiguration | None,
    now: datetime,
    statuses: dict[UUID, _BillingStatus],
) -> PlatformAlertOutcome:
    snapshot = _snapshot(check, alert)
    if alert is None:
        # The billing alert is gone or has moved to another team, so this copy can never run again.
        return _skipped(check, snapshot, now=now, disable=True)
    if not alert.enabled:
        return _skipped(check, snapshot, now=now)

    # A snooze set on the billing row after the backfill copied it lives only there. The platform
    # mutes rather than skips, so the check still tracks the total.
    muted = alert.snoozed_until is not None and alert.snoozed_until > now
    status = _billing_status(alert, statuses)
    if status.response is None:
        failed = CheckInput(threshold_breached=False, error_message=FETCH_FAILED, is_transient_error=True, muted=muted)
        return _verdict(check, snapshot, failed, now=now, skip=SkipReason.QUERY_FAILED)

    try:
        amount = current_period_amount(alert, status.response)
    except BillingAlertEvaluationError as error:
        # Billing's response, not the alert, is at fault, so it must not count toward breaking the copy:
        # a broken copy stays out of discovery after billing recovers.
        failed = CheckInput(threshold_breached=False, error_message=str(error), is_transient_error=True, muted=muted)
        return _verdict(check, snapshot, failed, now=now, skip=SkipReason.QUERY_FAILED)

    if amount is None:
        inconclusive = CheckInput(threshold_breached=False, is_inconclusive=True, muted=muted)
        return _verdict(check, snapshot, inconclusive, now=now, query_duration_ms=status.duration_ms)
    threshold = alert.threshold_value or Decimal("0")
    return _verdict(
        check,
        snapshot,
        CheckInput(threshold_breached=amount >= threshold, muted=muted),
        now=now,
        value=float(amount),
        query_duration_ms=status.duration_ms,
    )


def _snapshot(check: PlatformAlertCheckInput, alert: BillingAlertConfiguration | None) -> AlertSnapshot:
    # A billing alert does not group, so its state is the one instance on the empty key.
    instance = check.instance()
    return AlertSnapshot(
        state=AlertState(instance.state),
        cooldown=timedelta(minutes=check.cooldown_minutes),
        last_notified_at=instance.last_notified_at,
        # The billing row's snooze, because the copy keeps the one the backfill saw after a user clears it.
        snooze_until=alert.snoozed_until if alert is not None else instance.snooze_until,
        consecutive_failures=check.consecutive_failures,
        firing_started_at=instance.firing_started_at,
    )


def _billing_status(alert: BillingAlertConfiguration, statuses: dict[UUID, _BillingStatus]) -> _BillingStatus:
    """Fetches an organization's billing status once per batch key, however many of its alerts are due."""
    organization_id = alert.organization_id
    if organization_id not in statuses:
        try:
            response, duration_ms = fetch_billing_data(alert, alert.organization)
            statuses[organization_id] = _BillingStatus(response=response, duration_ms=duration_ms)
        except Exception as error:
            logger.warning("Platform billing data fetch failed", organization_id=str(organization_id), error=str(error))
            statuses[organization_id] = _BillingStatus(response=None)
    return statuses[organization_id]


def _verdict(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    check_input: CheckInput,
    *,
    now: datetime,
    value: float | None = None,
    query_duration_ms: int | None = None,
    skip: SkipReason | None = None,
) -> PlatformAlertOutcome:
    outcome = evaluate_alert_check(snapshot, check_input, now, policy=PLATFORM_DEFAULT_ALERT_POLICY)
    return _recorded(
        check,
        snapshot,
        outcome,
        now=now,
        notification=outcome.notification,
        muted_notification=outcome.muted_notification,
        notified=outcome.update_last_notified_at,
        value=value,
        error_message=outcome.error_message,
        query_duration_ms=query_duration_ms,
        skip=skip,
        disable=outcome.disable,
    )


def _skipped(
    check: PlatformAlertCheckInput, snapshot: AlertSnapshot, *, now: datetime, disable: bool = False
) -> PlatformAlertOutcome:
    """A check that reached no verdict. Recorded all the same, so its schedule moves on."""
    unchanged = ControlPlaneOutcome(new_state=snapshot.state, consecutive_failures=snapshot.consecutive_failures)
    return _recorded(check, snapshot, unchanged, now=now, skip=SkipReason.SOURCE_RULE, disable=disable)


def _recorded(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    outcome: Outcome,
    *,
    now: datetime,
    notification: NotificationAction = NotificationAction.NONE,
    muted_notification: NotificationAction = NotificationAction.NONE,
    notified: bool = False,
    value: float | None = None,
    error_message: str | None = None,
    query_duration_ms: int | None = None,
    skip: SkipReason | None = None,
    disable: bool = False,
) -> PlatformAlertOutcome:
    """The one place an outcome is built. Every path goes through the firing decision, because
    an outcome without an episode clears the start of a firing the alert is still in."""
    safe_record(increment_checks, SOURCE, notification.value)
    if skip is not None:
        safe_record(increment_checks_skipped, SOURCE, skip.value)
    if snapshot.state != outcome.new_state:
        safe_record(increment_state_transition, SOURCE, snapshot.state.value, outcome.new_state.value)
    failed = skip == SkipReason.QUERY_FAILED
    return PlatformAlertOutcome.ungrouped(
        configuration_id=check.id,
        evaluation_key=f"slot:{slot_of(check.next_check_at, now)}",
        consecutive_failures=outcome.consecutive_failures,
        kind=NOTIFICATION_EVENT_KINDS[notification],
        new_state=outcome.new_state.value,
        notified=notified,
        failed=failed,
        firing_episode=decide_firing_episode(snapshot, outcome, now, policy=PLATFORM_DEFAULT_ALERT_POLICY),
        value=value,
        muted_notification="" if muted_notification == NotificationAction.NONE else muted_notification.value,
        error_message=error_message,
        query_duration_ms=query_duration_ms,
        disable=disable,
        skipped=skip is not None and not failed,
        # A batch key is one team, and so one organization, so one group keeps a team's alerts in
        # one slot and one billing call. A broken alert is never discovered again.
        schedule_group=None if outcome.new_state == AlertState.BROKEN else SOURCE,
    )
