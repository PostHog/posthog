"""The platform's evaluator for appearance alerts: announce each identity that is new, or back.

An appearance never resolves by evaluation, so it holds no firing. Each announced identity gets an
instance at rest, which gives it a thread, a per-group mute and a slot `max_instances` can reclaim.
Its messages thread on the identity's own first-seen time, so a reappearance replies under the
message that announced it.

A check reads the window from where the last recorded check stopped to where the store is complete.
The window's end is recorded with the check's groups, so each window is announced once, however
late or often its checks run. Quiet hours hold no announcement here: the schedule runs no check
inside them, so what appeared then is announced by the first check after them.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Final

import structlog
from pydantic import ValidationError

from posthog.models import Team

from products.alerts_platform.backend.facade.appearance import AppearanceAlertConfig
from products.alerts_platform.backend.facade.contracts import (
    APPEARANCE_DETAIL_KEY,
    APPEARANCE_IDENTITY_LABEL,
    AlertDeliveryRequest,
    AlertEventKind,
    FiringEpisode,
    GroupOutcome,
    Occurrence,
    OccurrenceKind,
    OccurrenceWindow,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    SourceBatchEvaluation,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertKind, PlatformAlertState
from products.alerts_platform.backend.facade.grouping import (
    bounded_grouping_key,
    bounded_labels,
    delivery_parts,
    muted_value,
)
from products.alerts_platform.backend.facade.lifecycle import (
    NOTIFICATION_EVENT_KINDS,
    PLATFORM_DEFAULT_ALERT_POLICY,
    AlertSnapshot,
    AlertState,
    CheckInput,
    NotificationAction,
    decide_firing_episode,
    evaluate_alert_check,
)
from products.alerts_platform.backend.facade.payload import MAX_BATCH_PAYLOAD_BYTES, payload_bytes
from products.alerts_platform.backend.facade.scheduling import is_utc_datetime_blocked, parse_blocked_windows_tuples
from products.alerts_platform.backend.logic import occurrences, source_configs
from products.alerts_platform.backend.logic.platform_lifecycle import due_checks, slot_of

logger = structlog.get_logger(__name__)

# How many occurrences a check reads before its filters run. More than this in one window are left
# out and the overflow is marked as a lower bound. `max_instances` caps what is announced.
MAX_OCCURRENCES_READ: Final = 1000
# A group's source detail at most this large. With `MAX_INSTANCES_CEILING` groups, one check stays well
# inside `MAX_BATCH_PAYLOAD_BYTES`, so a check is never too large to record on its own.
MAX_DETAIL_BYTES: Final = 4096

_UNEXPECTED_ERROR: Final = "Alert check failed unexpectedly. PostHog has been notified."
_INVALID_CONFIG: Final = "The alert's configuration is no longer valid. Edit the alert to fix it."

Decision = tuple[PlatformAlertOutcome, AlertDeliveryRequest | None]


def event_ids_by_kind(source: SourceKind) -> dict[str, str]:
    return {
        AlertEventKind.APPEARED.value: f"${source.value}_alert_appeared",
        AlertEventKind.ERRORED.value: f"${source.value}_alert_errored",
        AlertEventKind.BROKEN.value: f"${source.value}_alert_broken",
    }


class _Reader:
    """One batch's reads of a store, shared by every check that starts its window at the same time."""

    def __init__(self, store: occurrences.RegistryStore, team_id: int, now: datetime) -> None:
        self.store = store
        self.team_id = team_id
        self.until = min(store.ready_until(team_id=team_id, now=now), now)
        self._windows: dict[datetime, OccurrenceWindow] = {}

    def window(self, since: datetime) -> OccurrenceWindow:
        if since >= self.until:
            return OccurrenceWindow(occurrences=())
        if since not in self._windows:
            self._windows[since] = self.store.appeared(
                team_id=self.team_id, since=since, until=self.until, limit=MAX_OCCURRENCES_READ
            )
        return self._windows[since]


def evaluate_appearance_batch(source: SourceKind, team_id: int, slot: str, cutoff: datetime) -> SourceBatchEvaluation:
    checks = due_checks(team_id, source.value, slot, cutoff, alert_kind=PlatformAlertKind.APPEARANCE)
    tz_name = Team.objects.filter(id=team_id).values_list("timezone", flat=True).first() if checks else None
    if tz_name is None:
        return SourceBatchEvaluation(outcomes=(), deliveries=())
    store = occurrences.store_for(source)
    try:
        reader = _Reader(store, team_id, cutoff)
    except Exception:
        logger.exception("Failed to read an occurrence store", source=source.value, team_id=team_id)
        return _collect([_failed(source, check, _UNEXPECTED_ERROR, transient=True, now=cutoff) for check in checks])
    return _collect([_evaluate(source, reader, check, now=cutoff, tz_name=tz_name) for check in checks])


def _evaluate(
    source: SourceKind, reader: _Reader, check: PlatformAlertCheckInput, *, now: datetime, tz_name: str
) -> Decision:
    try:
        config = AppearanceAlertConfig.model_validate(check.source_config)
    except ValidationError:
        return _failed(source, check, _INVALID_CONFIG, transient=False, now=now)
    created = check.created_at or now
    since = check.evaluated_until or created
    if _in_quiet_hours(check, now, tz_name):
        # A late check that runs inside quiet hours announces nothing and keeps its window, so the
        # first check after them announces what appeared.
        held = PlatformAlertOutcome(
            configuration_id=check.id,
            evaluation_key=f"window:{since.isoformat()}",
            consecutive_failures=0,
            grouping=check.grouping,
        )
        return held, None
    try:
        window = reader.window(since)
    except Exception:
        logger.exception("Failed to read an occurrence store", source=source.value, check_id=str(check.id))
        return _failed(source, check, _UNEXPECTED_ERROR, transient=True, now=now)

    keyed = {
        bounded_grouping_key(occurrence.identity_key): occurrence
        for occurrence in _one_per_identity(
            # An alert announces only what happened after it existed, whenever the fact was recorded.
            [o for o in window.occurrences if o.occurred_at >= created and config.matches(o.labels)]
        )
    }
    admission = check.admit(list(keyed), now=now)
    checked_until = max(reader.until, since)
    outcome = PlatformAlertOutcome(
        configuration_id=check.id,
        evaluation_key=f"window:{checked_until.isoformat()}",
        consecutive_failures=0,
        groups=tuple(_group(check, key, keyed[key], now=now) for key in keyed if key in admission.admitted),
        grouping=check.grouping,
        overflowed=admission.overflowed,
        overflow_is_lower_bound=window.truncated,
        evicted=tuple(sorted(admission.evicted)),
        evaluated_until=checked_until,
    )
    return outcome, _request(source, check, outcome)


def _in_quiet_hours(check: PlatformAlertCheckInput, now: datetime, tz_name: str) -> bool:
    try:
        return is_utc_datetime_blocked(now, tz_name, parse_blocked_windows_tuples(check.schedule_restriction))
    except Exception:
        logger.exception("Unparseable schedule restriction on an appearance alert", check_id=str(check.id))
        return False


def _one_per_identity(found: Sequence[Occurrence]) -> list[Occurrence]:
    """An outcome names each group once. A new identity that also came back in the window is announced as new."""
    kept: dict[str, Occurrence] = {}
    for occurrence in found:
        if occurrence.identity_key not in kept or occurrence.kind == OccurrenceKind.NEW:
            kept[occurrence.identity_key] = occurrence
    return list(kept.values())


def _group(check: PlatformAlertCheckInput, key: str, occurrence: Occurrence, *, now: datetime) -> GroupOutcome:
    """One announcement. The instance stays at rest, and the history row keys its thread on first sight.

    A snoozed alert or group records the occurrence and does not announce it later, because the
    window it was in is done.
    """
    snooze_until = check.instance(key).snooze_until
    held = snooze_until is not None and snooze_until > now
    return GroupOutcome(
        grouping_key=key,
        kind=AlertEventKind.CHECK if held else AlertEventKind.APPEARED,
        new_state=PlatformAlertState.NOT_FIRING.value,
        notified=not held,
        firing_episode=FiringEpisode(started_at=occurrence.first_seen_at, ended=True),
        # First, because a group stores only its first few labels and the identity is the one that names it.
        labels=bounded_labels({APPEARANCE_IDENTITY_LABEL: occurrence.identity_key, **occurrence.labels}),
        muted_notification=NotificationAction.FIRE.value if held else "",
        source_detail={
            **_bounded_detail(occurrence.detail),
            APPEARANCE_DETAIL_KEY: occurrence.kind.value,
            "first_seen_at": occurrence.first_seen_at.isoformat(),
            "occurred_at": occurrence.occurred_at.isoformat(),
        },
    )


def _bounded_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """The source's detail, or none of it when it is too large, so one check always fits a batch payload."""
    return detail if payload_bytes(detail) <= MAX_DETAIL_BYTES else {}


def _failed(
    source: SourceKind, check: PlatformAlertCheckInput, message: str, *, transient: bool, now: datetime
) -> Decision:
    """A check that read nothing. Its window stays where it was, so the next check reads it."""
    instance = check.instance()
    muted = check.snooze_until is not None and check.snooze_until > now
    snapshot = AlertSnapshot(
        state=AlertState(instance.state),
        cooldown=timedelta(minutes=check.cooldown_minutes),
        last_notified_at=instance.last_notified_at,
        snooze_until=instance.snooze_until,
        consecutive_failures=check.consecutive_failures,
    )
    result = evaluate_alert_check(
        snapshot,
        CheckInput(threshold_breached=False, error_message=message, is_transient_error=transient, muted=muted),
        now,
        policy=PLATFORM_DEFAULT_ALERT_POLICY,
    )
    outcome = PlatformAlertOutcome.ungrouped(
        configuration_id=check.id,
        evaluation_key=f"slot:{slot_of(check.next_check_at, now)}",
        consecutive_failures=result.consecutive_failures,
        kind=NOTIFICATION_EVENT_KINDS[result.notification],
        new_state=result.new_state.value,
        notified=result.update_last_notified_at,
        failed=True,
        firing_episode=decide_firing_episode(snapshot, result, now, policy=PLATFORM_DEFAULT_ALERT_POLICY),
        muted_notification=muted_value(result),
        error_message=result.error_message,
        disable=result.disable,
    )
    return outcome, _request(source, check, outcome)


def _request(
    source: SourceKind, check: PlatformAlertCheckInput, outcome: PlatformAlertOutcome
) -> AlertDeliveryRequest | None:
    announced = any(group.notified for group in outcome.groups) or (
        outcome.failure is not None and outcome.failure.notified
    )
    if not announced:
        return None
    spec = source_configs.spec(source, PlatformAlertKind.APPEARANCE)
    alert_url = spec.alert_url if spec is not None else None
    return AlertDeliveryRequest(
        source=source,
        team_id=check.team_id,
        configuration_id=str(check.id),
        evaluation_key=outcome.evaluation_key,
        destination_alert_id=str(check.destination_alert_id),
        event_ids_by_kind=event_ids_by_kind(source),
        source_alert_url=alert_url(check.team_id, check.id) if alert_url is not None else None,
        owned_by_platform=check.owned_by_platform,
        overflowed=outcome.overflowed,
        overflow_is_lower_bound=outcome.overflow_is_lower_bound,
        parts=delivery_parts(outcome),
        alert_kind=PlatformAlertKind.APPEARANCE,
    )


def _collect(decided: Sequence[Decision]) -> SourceBatchEvaluation:
    """The batch, held to one payload. A check past it keeps its due time and its window."""
    outcomes: list[PlatformAlertOutcome] = []
    deliveries: list[AlertDeliveryRequest] = []
    spent = 0
    deferred = 0
    for outcome, delivery in decided:
        size = payload_bytes(outcome) + (payload_bytes(delivery) if delivery is not None else 0)
        if spent + size > MAX_BATCH_PAYLOAD_BYTES:
            deferred += 1
            continue
        spent += size
        outcomes.append(outcome)
        if delivery is not None:
            deliveries.append(delivery)
    return SourceBatchEvaluation(outcomes=tuple(outcomes), deliveries=tuple(deliveries), omitted=deferred)
