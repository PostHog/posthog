"""Evaluation of due billing alerts on the shared alerts platform.

A parallel run. Production billing evaluates the same alerts against `BillingAlertConfiguration`
and is the only stack that notifies anyone. This decides what the platform would have said and
delivers nothing.

Each platform row resolves to its production alert through `legacy_configuration_id`, because
`evaluate_billing_alert` reads the metric and the bound off that model. The verdict comes from
billing's own wrappers around the shared machine, applied to the platform's own state. Production's
claim rows are never read or written: the evaluation date and the attempt count live in the
configuration's source state instead.

A billing check retries its evaluation date on billing's own backoff, so every outcome here names
its next due time rather than taking the platform's fixed advance.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.facade.api import due_checks, slot_of
from products.alerts_platform.backend.facade.contracts import (
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SkipReason,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.lifecycle import (
    BILLING_ALERT_POLICY,
    NOTIFICATION_EVENT_KINDS,
    AlertCheckOutcome,
    AlertSnapshot,
    AlertState,
    ControlPlaneOutcome,
    NotificationAction,
    Outcome,
    decide_firing_episode,
)
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_checks,
    increment_checks_skipped,
    increment_state_transition,
    record_scheduler_lag,
    safe_record,
)
from products.billing_alerts.backend.logic.evaluator import (
    delayed_evaluation_date,
    evaluate_billing_alert,
    fetch_billing_data,
)
from products.billing_alerts.backend.logic.state_machine import (
    MAX_EVALUATION_ATTEMPTS,
    evaluate_alert_check,
    evaluate_alert_failure,
    evaluation_retry_delay,
    next_billing_alert_check_at,
)
from products.billing_alerts.backend.models import BillingAlertConfiguration

logger = structlog.get_logger(__name__)

SOURCE = SourceKind.BILLING.value


@frozen
class _BillingData:
    """One organization's billing status, fetched once per batch, or why it could not be."""

    response: dict[str, Any] | None = None
    duration_ms: int | None = None
    error: str | None = None
    is_transient_error: bool = False


@frozen
class EvaluationAttempt:
    """Which evaluation date a check covers and how many tries that date has used."""

    evaluation_date: date
    configuration_revision: int
    number: int

    @property
    def has_retries_left(self) -> bool:
        return self.number < MAX_EVALUATION_ATTEMPTS

    @property
    def evaluation_key(self) -> str:
        # The attempt is part of the key because every retry of a date is its own history row.
        # History deduplicates on the key, so retries sharing one would overwrite each other.
        return f"date:{self.evaluation_date.isoformat()}:rev:{self.configuration_revision}:attempt:{self.number}"

    def state(self, *, completed: bool) -> dict[str, Any]:
        return {
            "evaluation_date": self.evaluation_date.isoformat(),
            "configuration_revision": self.configuration_revision,
            "attempt": self.number,
            "completed": completed,
        }


def parse_evaluation_key(key: str) -> EvaluationAttempt | None:
    """The attempt a check's evaluation key names, or None for a skipped check's slot key."""
    match key.split(":"):
        case ["date", evaluation_date, "rev", revision, "attempt", number]:
            try:
                return EvaluationAttempt(
                    evaluation_date=date.fromisoformat(evaluation_date),
                    configuration_revision=int(revision),
                    number=int(number),
                )
            except ValueError:
                return None
        case _:
            return None


def evaluate_billing_batch(team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    """Decides every due billing check in one batch key. Writes nothing."""
    checks = due_checks(team_id, SOURCE, slot, cutoff)
    if not checks:
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    legacy_ids = [check.legacy_configuration_id for check in checks if check.legacy_configuration_id is not None]
    organization_id = Team.objects.values_list("organization_id", flat=True).get(id=team_id)
    # Scoped to the batch's team and its organization, so a copy can only read an alert it belongs to.
    alerts = {
        alert.id: alert
        for alert in BillingAlertConfiguration.objects.filter(
            id__in=legacy_ids, organization_id=organization_id, team_id=team_id
        ).select_related("organization")
    }
    billing_data: dict[UUID, _BillingData] = {}

    # Read before any billing call, so the fetches do not count as scheduler lag.
    started_at = datetime.now(UTC)
    for check in checks:
        if check.next_check_at is not None:
            lag_ms = int((started_at - check.next_check_at).total_seconds() * 1000)
            if lag_ms > 0:
                safe_record(record_scheduler_lag, SOURCE, lag_ms)

    outcomes: list[PlatformAlertOutcome] = []
    for check in checks:
        alert = alerts.get(check.legacy_configuration_id) if check.legacy_configuration_id else None
        outcomes.append(_decide(check, alert, cutoff, billing_data))
    return SourceBatchEvaluation(outcomes=tuple(outcomes), deliveries=())


def _decide(
    check: PlatformAlertCheckInput,
    alert: BillingAlertConfiguration | None,
    now: datetime,
    billing_data: dict[UUID, _BillingData],
) -> PlatformAlertOutcome:
    snapshot = _snapshot(check, alert)
    if alert is None or alert.team_id is None:
        # The production alert is gone, or its organization is being deleted, so this copy can
        # never be compared again.
        return _skipped(check, snapshot, now=now, next_check_at=None, disable=True)
    # Production does not evaluate a disabled, snoozed or broken alert. The legacy row is read,
    # because a change made after the backfill copied the row lives only there.
    snoozed = alert.snoozed_until is not None and alert.snoozed_until > now
    # Production also marks a date's claim completed and skips it if the date comes due again.
    attempt = None
    if alert.enabled and not snoozed and alert.state != BillingAlertConfiguration.State.BROKEN:
        attempt = _attempt(check, alert, now)
    if attempt is None:
        return _skipped(check, snapshot, now=now, next_check_at=next_billing_alert_check_at(alert, now))

    data = _billing_data(alert, billing_data)
    if data.response is None:
        return _failed(
            check,
            snapshot,
            alert,
            attempt,
            now=now,
            error_message=data.error or "Billing alert data fetch failed.",
            is_transient_error=data.is_transient_error,
        )

    try:
        evaluation = evaluate_billing_alert(
            alert,
            now=now,
            billing_response=data.response,
            query_duration_ms=data.duration_ms,
            evaluation_date=attempt.evaluation_date,
        )
    except Exception as error:
        logger.exception("Platform billing check failed", check_id=str(check.id), error=str(error))
        return _failed(
            check,
            snapshot,
            alert,
            attempt,
            now=now,
            error_message="Billing alert evaluation failed.",
            is_transient_error=False,
        )

    outcome = evaluate_alert_check(snapshot, evaluation, now)
    return _settled(
        check,
        snapshot,
        outcome,
        alert,
        attempt,
        now=now,
        retry=evaluation.is_inconclusive,
        value=float(evaluation.current_value) if evaluation.current_value is not None else None,
        error_message=outcome.error_message,
        query_duration_ms=evaluation.query_duration_ms,
    )


def _snapshot(check: PlatformAlertCheckInput, alert: BillingAlertConfiguration | None) -> AlertSnapshot:
    """The platform's own state. The cooldown is production's, read off the legacy row, because
    an edit to it after the backfill lives only there."""
    cooldown = timedelta(hours=alert.cooldown_hours) if alert else timedelta(minutes=check.cooldown_minutes)
    return AlertSnapshot(
        state=AlertState(check.state),
        cooldown=cooldown,
        last_notified_at=check.last_notified_at,
        snooze_until=check.snooze_until,
        consecutive_failures=check.consecutive_failures,
        firing_started_at=check.firing_started_at,
    )


def _attempt(
    check: PlatformAlertCheckInput, alert: BillingAlertConfiguration, now: datetime
) -> EvaluationAttempt | None:
    """The date this check covers. A date with retries left keeps its date and counts the try.

    Returns None when the date this check would cover is already settled for this revision.
    """
    state = check.source_state
    revision = alert.configuration_revision
    stored_date = state.get("evaluation_date")
    same_revision = state.get("configuration_revision") == revision
    if stored_date is not None and same_revision and not state.get("completed"):
        return EvaluationAttempt(
            evaluation_date=date.fromisoformat(stored_date),
            configuration_revision=revision,
            number=int(state.get("attempt", 0)) + 1,
        )
    # Production's date rule without production's pending date. The platform keeps its own
    # pending date in source state, read above.
    expected = delayed_evaluation_date(alert, now)
    if stored_date == expected.isoformat() and same_revision and state.get("completed"):
        return None
    return EvaluationAttempt(evaluation_date=expected, configuration_revision=revision, number=1)


def _billing_data(alert: BillingAlertConfiguration, cache: dict[UUID, _BillingData]) -> _BillingData:
    """Fetches an organization's billing status once per batch, as production does per group."""
    organization_id = alert.organization_id
    if organization_id in cache:
        return cache[organization_id]
    try:
        response, duration_ms = fetch_billing_data(alert, alert.organization)
        data = _BillingData(response=response, duration_ms=duration_ms)
    except Exception as error:
        logger.warning("Platform billing data fetch failed", organization_id=str(organization_id), error=str(error))
        data = _BillingData(error="Billing alert data fetch failed.", is_transient_error=True)
    cache[organization_id] = data
    return data


def _failed(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    alert: BillingAlertConfiguration,
    attempt: EvaluationAttempt,
    *,
    now: datetime,
    error_message: str,
    is_transient_error: bool,
) -> PlatformAlertOutcome:
    failure = evaluate_alert_failure(
        snapshot,
        error_message=error_message,
        is_transient_error=is_transient_error,
        attempts_remaining=attempt.has_retries_left,
    )
    return _settled(
        check,
        snapshot,
        failure,
        alert,
        attempt,
        now=now,
        retry=is_transient_error,
        error_message=error_message,
        skip=SkipReason.QUERY_FAILED,
    )


def _settled(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    outcome: AlertCheckOutcome,
    alert: BillingAlertConfiguration,
    attempt: EvaluationAttempt,
    *,
    now: datetime,
    retry: bool,
    value: float | None = None,
    error_message: str | None = None,
    query_duration_ms: int | None = None,
    skip: SkipReason | None = None,
) -> PlatformAlertOutcome:
    """A check that reached a verdict. Retries its date on billing's backoff while attempts remain,
    and otherwise settles the date and waits for the next one, as production's commit does."""
    retrying = retry and attempt.has_retries_left
    next_check_at = (
        now + evaluation_retry_delay(attempt.number) if retrying else next_billing_alert_check_at(alert, now)
    )
    return _recorded(
        check,
        snapshot,
        outcome,
        now=now,
        evaluation_key=attempt.evaluation_key,
        notification=outcome.notification,
        notified=outcome.update_last_notified_at,
        value=value,
        error_message=error_message,
        query_duration_ms=query_duration_ms,
        skip=skip,
        disable=outcome.disable,
        next_check_at=next_check_at,
        source_state=attempt.state(completed=not retrying),
    )


def _skipped(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    *,
    now: datetime,
    next_check_at: datetime | None,
    disable: bool = False,
) -> PlatformAlertOutcome:
    """A check that reached no verdict. Recorded all the same, so its schedule moves on."""
    unchanged = ControlPlaneOutcome(new_state=snapshot.state, consecutive_failures=snapshot.consecutive_failures)
    return _recorded(
        check,
        snapshot,
        unchanged,
        now=now,
        evaluation_key=f"slot:{slot_of(check.next_check_at, now)}",
        skip=SkipReason.SOURCE_RULE,
        disable=disable,
        next_check_at=next_check_at,
    )


def _recorded(
    check: PlatformAlertCheckInput,
    snapshot: AlertSnapshot,
    outcome: Outcome,
    *,
    now: datetime,
    evaluation_key: str,
    notification: NotificationAction = NotificationAction.NONE,
    notified: bool = False,
    value: float | None = None,
    error_message: str | None = None,
    query_duration_ms: int | None = None,
    skip: SkipReason | None = None,
    disable: bool = False,
    next_check_at: datetime | None = None,
    source_state: dict[str, Any] | None = None,
) -> PlatformAlertOutcome:
    """The one place an outcome is built. Every path goes through the firing decision, because
    an outcome without an episode clears the start of a firing the alert is still in."""
    safe_record(increment_checks, SOURCE, notification.value)
    if skip is not None:
        safe_record(increment_checks_skipped, SOURCE, skip.value)
    if check.state != outcome.new_state.value:
        safe_record(increment_state_transition, SOURCE, check.state, outcome.new_state.value)
    return PlatformAlertOutcome(
        configuration_id=check.id,
        evaluation_key=evaluation_key,
        kind=NOTIFICATION_EVENT_KINDS[notification],
        new_state=outcome.new_state.value,
        notified=notified,
        consecutive_failures=outcome.consecutive_failures,
        firing_episode=decide_firing_episode(snapshot, outcome, now, policy=BILLING_ALERT_POLICY),
        value=value,
        error_message=error_message,
        query_duration_ms=query_duration_ms,
        disable=disable,
        next_check_at=next_check_at,
        source_state=source_state,
    )
