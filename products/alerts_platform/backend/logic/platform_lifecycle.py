"""Reads and writes for the skeleton shared alert tables.

A source decides whether its data breached; everything about what that means for the alert,
and every write to these rows, stays here. A source never holds one of these models.
"""

from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Final
from uuid import UUID

from django.db import connection, transaction
from django.db.models import Q, QuerySet
from django.utils import timezone as django_timezone

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    CheckFailure,
    Grouping,
    GroupingMode,
    GroupOutcome,
    HandbackRefusal,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertConfigurationEdit,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    PlatformHandback,
    PlatformOwnershipHandover,
    SourceKind,
    source_condition,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.alerts_platform.backend.facade.lifecycle import NotificationAction
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_groups_over_cap,
    increment_history_rows_dropped,
    increment_instances_reaped,
    safe_record,
)
from products.alerts_platform.backend.facade.scheduling import (
    advance_schedule,
    compute_shard_offset_seconds,
    compute_team_shard_offset_seconds,
    parse_blocked_windows_tuples,
    to_recurrence_interval,
    validate_and_normalize_schedule_start_time,
)
from products.alerts_platform.backend.logic import delivery_holds
from products.alerts_platform.backend.logic.platform_alert_events import PlatformAlertEventRow, insert_events
from products.alerts_platform.backend.models import (
    PlatformAlert,
    PlatformAlertConfiguration,
    PlatformAlertDeliveryHold,
    PlatformAlertThread,
)


def due_q(moment: datetime) -> Q:
    """Configurations a check is owed at `moment`. The read and the write share it, because the
    write skips a row already advanced past it and that is what makes a replay safe."""
    return Q(next_check_at__lte=moment) | Q(next_check_at__isnull=True)


def _instances_by_configuration(
    team_id: int, configurations: Sequence[PlatformAlertConfiguration]
) -> dict[str, list[PlatformAlert]]:
    """Every runtime row each configuration has. A configuration with none has never been evaluated."""
    found: dict[str, list[PlatformAlert]] = {}
    rows = PlatformAlert.objects.for_team(team_id).filter(configuration__in=configurations).order_by("grouping_key")
    for alert in rows:
        found.setdefault(str(alert.configuration_id), []).append(alert)
    return found


@frozen
class _InstanceKey:
    configuration_id: str
    grouping_key: str


def _instances(team_id: int, keys: Collection[_InstanceKey]) -> dict[_InstanceKey, PlatformAlert]:
    rows = PlatformAlert.objects.for_team(team_id).filter(
        configuration_id__in={key.configuration_id for key in keys},
        grouping_key__in={key.grouping_key for key in keys},
    )
    found = {
        _InstanceKey(configuration_id=str(row.configuration_id), grouping_key=row.grouping_key): row for row in rows
    }
    # The filter crosses every configuration with every key, so it can return pairs nobody asked for.
    return {key: row for key, row in found.items() if key in keys}


def _alerts_for_write(
    team_id: int, configurations: Sequence[PlatformAlertConfiguration], wanted: Collection[_InstanceKey]
) -> dict[_InstanceKey, PlatformAlert]:
    """Every runtime row these configurations have, plus a new one for each wanted group with room.

    One read serves the existing rows, the counts the cap needs, and the empty-key row a failure
    states. A group past `max_instances` gets no row, and so no write and no history. A source admits
    groups before it reports them, so this is the backstop for one that did not.
    """
    loaded = {
        _InstanceKey(configuration_id=configuration_id, grouping_key=alert.grouping_key): alert
        for configuration_id, alerts in _instances_by_configuration(team_id, configurations).items()
        for alert in alerts
    }
    by_id = {str(configuration.id): configuration for configuration in configurations}
    held: dict[str, int] = {}
    for key in loaded:
        held[key.configuration_id] = held.get(key.configuration_id, 0) + 1
    missing: list[_InstanceKey] = []
    over_cap: dict[str, int] = {}
    for key in wanted:
        if key in loaded:
            continue
        configuration = by_id[key.configuration_id]
        if held.get(key.configuration_id, 0) >= Grouping.from_stored(configuration.grouping).max_instances:
            over_cap[configuration.source_kind] = over_cap.get(configuration.source_kind, 0) + 1
            continue
        held[key.configuration_id] = held.get(key.configuration_id, 0) + 1
        missing.append(key)
    for source_kind, count in over_cap.items():
        safe_record(increment_groups_over_cap, source_kind, count)
    if missing:
        # ignore_conflicts leans on the unique constraint, so a concurrent cycle creating the
        # same row is not an error. `for_team` because these models are fail-closed and a
        # Temporal activity has no ambient scope; the rows still carry `team_id` themselves,
        # because a queryset filter does not propagate into row creation.
        PlatformAlert.objects.for_team(team_id).bulk_create(
            [
                PlatformAlert(team_id=team_id, configuration=by_id[key.configuration_id], grouping_key=key.grouping_key)
                for key in missing
            ],
            ignore_conflicts=True,
        )
        loaded.update(_instances(team_id, missing))
    return loaded


def _at_rest(now: datetime) -> Q:
    """Rows that hold a slot and nothing else, as `InstanceCheckState.at_rest` reads an instance."""
    return Q(state=PlatformAlert.State.NOT_FIRING) & (Q(snooze_until__isnull=True) | Q(snooze_until__lte=now))


# Long enough that a group which resolves and fires again inside a day keeps its cooldown.
REAP_AFTER: Final = timedelta(hours=24)


def _reap(
    team_id: int,
    configurations: Sequence[PlatformAlertConfiguration],
    now: datetime,
    *,
    returned: Collection[_InstanceKey],
) -> None:
    """Deletes instances that hold a slot and nothing else, so a stale group frees its place.

    Only an instance that is not firing, not muted, and that no check returned for longer than both
    `REAP_AFTER` and its cooldown. A configuration whose checks fail returns no groups, so its
    instances look unseen without being gone. The caller passes only configurations whose check
    succeeded.
    """
    # An ungrouped configuration's one instance is returned by every check, so it has nothing to reap.
    healthy = {str(c.id): c for c in configurations if Grouping.from_stored(c.grouping).mode != GroupingMode.SINGLE}
    if not healthy:
        return
    candidates = (
        PlatformAlert.objects.for_team(team_id)
        .filter(_at_rest(now), configuration_id__in=list(healthy), last_seen_at__lt=now - REAP_AFTER)
        .values_list("id", "configuration_id", "grouping_key", "last_seen_at")
    )
    reaped: dict[str, list[UUID]] = {}
    for alert_id, configuration_id, grouping_key, last_seen_at in candidates:
        if _InstanceKey(configuration_id=str(configuration_id), grouping_key=grouping_key) in returned:
            continue
        configuration = healthy[str(configuration_id)]
        if configuration.snooze_until is not None and configuration.snooze_until > now:
            continue
        if last_seen_at is None or last_seen_at >= now - timedelta(minutes=configuration.cooldown_minutes):
            continue
        reaped.setdefault(configuration.source_kind, []).append(alert_id)
    for source_kind, ids in reaped.items():
        PlatformAlert.objects.for_team(team_id).filter(id__in=ids).delete()
        safe_record(increment_instances_reaped, source_kind, len(ids))


def _evict(
    team_id: int,
    configurations: Sequence[PlatformAlertConfiguration],
    by_id: dict[str, PlatformAlertOutcome],
    now: datetime,
) -> None:
    """Deletes the resting instances a check evicted, so the groups that took their slots pass the cap.

    The filter repeats the check's notion of at rest, because the row may have changed since the
    check read it, and deleting a firing or muted instance would lose its state.
    """
    doomed: dict[str, Q] = {}
    for configuration in configurations:
        evicted = by_id[str(configuration.id)].evicted
        if not evicted or Grouping.from_stored(configuration.grouping).mode == GroupingMode.SINGLE:
            continue
        if configuration.snooze_until is not None and configuration.snooze_until > now:
            continue
        doomed[configuration.source_kind] = doomed.get(configuration.source_kind, Q()) | Q(
            configuration_id=configuration.id, grouping_key__in=evicted
        )
    for source_kind, rows in doomed.items():
        deleted, _ = PlatformAlert.objects.for_team(team_id).filter(rows, _at_rest(now)).delete()
        if deleted:
            safe_record(increment_instances_reaped, source_kind, deleted)


def suppressed() -> Q:
    """Configurations a check status holds back.

    BROKEN only. A mute holds an announcement rather than a check, so a snoozed alert is
    discovered and evaluated like any other and its state keeps tracking reality.

    Discovery and the batch read both reach for this rather than each writing the predicate out.
    If the two disagreed, a broken alert would be dispatched by one and dropped by the other,
    every tick, in silence.
    """
    return Q(check_status=PlatformAlertConfiguration.CheckStatus.BROKEN)


RULE_METADATA_FIELDS: Final = ("labels", "annotations")


def _due(team_id: int, source_kind: str, cutoff: datetime) -> QuerySet[PlatformAlertConfiguration]:
    return (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .defer(*RULE_METADATA_FIELDS)
        .filter(enabled=True, source_kind=source_kind)
        .filter(due_q(cutoff))
        .exclude(suppressed())
    )


def due_check_ids(
    team_id: int, source_kind: str, slot: str, cutoff: datetime, *, exclude: Collection[str] = (), limit: int
) -> tuple[str, ...]:
    """The first `limit` due ids of one batch key, in id order, without reading their runtime rows.

    For a source that admits ids in rounds. A round reads only ids, so a large batch does not
    reload every configuration and its alert row each time a check finishes.
    """
    rows = (
        _due(team_id, source_kind, cutoff)
        .exclude(id__in=list(exclude))
        .order_by("id")
        .values_list("id", "next_check_at")
    )
    ids: list[str] = []
    for configuration_id, next_check_at in rows.iterator():
        if slot_of(next_check_at, cutoff) != slot:
            continue
        ids.append(str(configuration_id))
        if len(ids) == limit:
            break
    return tuple(ids)


def due_checks(
    team_id: int, source_kind: str, slot: str, cutoff: datetime, *, configuration_ids: Collection[str] | None = None
) -> tuple[PlatformAlertCheckInput, ...]:
    """Every configuration in one batch key, with its runtime state, ready to evaluate.

    `configuration_ids` narrows the batch to those rows, for a source that evaluates one check at
    a time and must still read nothing the batch would not.
    """
    due = _due(team_id, source_kind, cutoff)
    if configuration_ids is not None:
        due = due.filter(id__in=list(configuration_ids))
    # Ordered so a retried attempt keeps the same alerts under any downstream cap.
    configurations = list(due.order_by("id"))
    configurations = [c for c in configurations if slot_of(c.next_check_at, cutoff) == slot]
    if not configurations:
        return ()

    instances = _instances_by_configuration(team_id, configurations)
    return tuple(_check(c, instances.get(str(c.id), [])) for c in configurations)


def _check(c: PlatformAlertConfiguration, alerts: Sequence[PlatformAlert]) -> PlatformAlertCheckInput:
    return PlatformAlertCheckInput(
        id=c.id,
        team_id=c.team_id,
        name=c.name,
        source_config=c.source_config,
        check_interval_minutes=c.check_interval_minutes,
        evaluation_periods=c.evaluation_periods,
        datapoints_to_alarm=c.datapoints_to_alarm,
        cooldown_minutes=c.cooldown_minutes,
        schedule_restriction=c.schedule_restriction,
        next_check_at=c.next_check_at,
        consecutive_failures=c.consecutive_failures,
        legacy_configuration_id=c.legacy_configuration_id,
        check_status=c.check_status,
        snooze_until=c.snooze_until,
        instances=tuple(_composed(c, alert) for alert in alerts),
        grouping=Grouping.from_stored(c.grouping),
        owned_by_platform=c.owner == PlatformAlertConfiguration.Owner.PLATFORM,
        recurrence_unit=c.recurrence_unit,
        anchor_time=c.anchor_time,
    )


def _composed(configuration: PlatformAlertConfiguration, alert: PlatformAlert | None) -> InstanceCheckState:
    return InstanceCheckState.composed(
        grouping_key=alert.grouping_key if alert else "",
        state=alert.state if alert else PlatformAlert.State.NOT_FIRING.value,
        check_status=configuration.check_status,
        configuration_snooze_until=configuration.snooze_until,
        snooze_until=alert.snooze_until if alert else None,
        last_notified_at=alert.last_notified_at if alert else None,
        firing_started_at=alert.firing_started_at if alert else None,
        last_seen_at=alert.last_seen_at if alert else None,
    )


def slot_of(next_check_at: datetime | None, cutoff: datetime) -> str:
    """The minute a configuration is due for. One that has never been checked has no due time
    of its own, so it belongs to the tick that found it.

    The single definition: discovery mints a key with it and this filters rows back down to
    one. If the two ever disagreed, every alert would evaluate nothing, silently.
    """
    return (next_check_at or cutoff).replace(second=0, microsecond=0).isoformat()


def _condition_snapshot(configuration: PlatformAlertConfiguration) -> dict[str, object]:
    """What the check was evaluated against, as a message and a comparison need to read it.

    Taken from the configuration when the outcome is recorded rather than shipped with it, because
    a source's copy would cost Temporal payload on every batch.

    One path can write a configuration between an evaluation and its record, so the snapshot is
    evaluation-time by convention rather than by construction: a hand-run backfill's
    `upsert_configuration`, for a configuration already copied whose source row changed since. The
    row then states the new condition beside a verdict measured against the old one. Carry the
    snapshot on the outcome if that stops being acceptable. A logs evaluation also upserts a drifted
    copy, but before it evaluates, so its snapshot matches its verdict.

    The source's bound is flattened in beside the platform's own fields, so a reader finds it at
    the top level whatever shape the source gives it.
    """
    return {
        **source_condition(configuration.source_config),
        "evaluation_periods": configuration.evaluation_periods,
        "check_interval_minutes": configuration.check_interval_minutes,
        "datapoints_to_alarm": configuration.datapoints_to_alarm,
        "cooldown_minutes": configuration.cooldown_minutes,
    }


# The `alert_id` of a history row that belongs to the check rather than to a group. The column is in
# the table's sort key, which rejects Nullable, so the nil UUID stands in for "no instance".
CONFIGURATION_ROW_ALERT_ID: Final = UUID(int=0)


def _event_row(
    configuration: PlatformAlertConfiguration,
    outcome: PlatformAlertOutcome,
    verdict: GroupOutcome | CheckFailure,
    *,
    alert: PlatformAlert | None,
    previous_state: str,
    now: datetime,
) -> PlatformAlertEventRow:
    group = verdict if isinstance(verdict, GroupOutcome) else None
    return event_row(
        configuration,
        alert=alert,
        evaluation_key=outcome.evaluation_key,
        kind=verdict.kind.value,
        previous_state=previous_state,
        state=verdict.new_state,
        # The whole episode, ended or not. A resolve names the firing it closed, which is what a
        # thread key needs and what the alert row no longer holds.
        episode_started_at=verdict.firing_episode.started_at if verdict.firing_episode else None,
        value=group.value if group else None,
        labels=group.labels if group else {},
        query_duration_ms=outcome.query_duration_ms,
        error_message=outcome.error_message,
        consecutive_failures=outcome.consecutive_failures,
        muted_notification=verdict.muted_notification,
        source_detail=verdict.source_detail,
        now=now,
    )


def event_row(
    configuration: PlatformAlertConfiguration,
    *,
    alert: PlatformAlert | None,
    evaluation_key: str,
    kind: str,
    previous_state: str,
    state: str,
    episode_started_at: datetime | None,
    consecutive_failures: int,
    now: datetime,
    value: float | None = None,
    labels: dict[str, str] | None = None,
    query_duration_ms: int | None = None,
    error_message: str | None = None,
    muted_notification: str = "",
    source_detail: dict[str, Any] | None = None,
) -> PlatformAlertEventRow:
    """One history row for a configuration, with the snapshots every row carries."""
    return PlatformAlertEventRow(
        team_id=configuration.team_id,
        source_kind=configuration.source_kind,
        configuration_id=configuration.id,
        alert_id=alert.id if alert else CONFIGURATION_ROW_ALERT_ID,
        grouping_key=alert.grouping_key if alert else "",
        evaluation_key=evaluation_key,
        kind=kind,
        alert_name=configuration.name,
        previous_state=previous_state,
        state=state,
        episode_started_at=episode_started_at,
        value=value,
        labels=labels or {},
        condition_snapshot=_condition_snapshot(configuration),
        source_config_snapshot=configuration.source_config,
        query_duration_ms=query_duration_ms,
        error_message=error_message,
        consecutive_failures=consecutive_failures,
        muted_notification=muted_notification,
        occurred_at=now,
        source_detail=source_detail or {},
    )


def record_history(team_id: int, rows: Sequence[PlatformAlertEventRow]) -> None:
    recorded = insert_events(team_id, rows)
    if recorded < len(rows):
        # One batch holds one source's checks.
        safe_record(increment_history_rows_dropped, rows[0].source_kind, len(rows) - recorded)


def _shard_offset_seconds(configuration: PlatformAlertConfiguration, outcome: PlatformAlertOutcome) -> int:
    if outcome.schedule_group is None:
        return compute_shard_offset_seconds(configuration.id, configuration.check_interval_minutes)
    return compute_team_shard_offset_seconds(
        configuration.team_id, configuration.check_interval_minutes, group=outcome.schedule_group
    )


_CHECK_STATUSES: Final = frozenset(PlatformAlertConfiguration.CheckStatus.values) - {
    PlatformAlertConfiguration.CheckStatus.OK.value
}


def _check_status(configuration: PlatformAlertConfiguration, outcome: PlatformAlertOutcome) -> str:
    """BROKEN over ERRORED over OK, because a check is as bad as its worst verdict.

    A failure that the policy rides through leaves the status where it was, so only the machine's
    ERRORED or BROKEN moves it.
    """
    if outcome.failure is not None:
        failed = outcome.failure.new_state
        return failed if failed in _CHECK_STATUSES else configuration.check_status
    if outcome.skipped:
        return configuration.check_status
    states = {group.new_state for group in outcome.groups}
    for status in (PlatformAlertConfiguration.CheckStatus.BROKEN, PlatformAlertConfiguration.CheckStatus.ERRORED):
        if status.value in states:
            return status.value
    return PlatformAlertConfiguration.CheckStatus.OK.value


def _without_stale_groups(
    configuration: PlatformAlertConfiguration, outcome: PlatformAlertOutcome
) -> PlatformAlertOutcome:
    """The outcome, or the outcome with its groups dropped when the check ran under another grouping.

    An edit that changes the grouping deletes the instances, so recording a stale check's groups
    would bring back instances keyed for the old grouping and announce them. The rest of the
    outcome still holds: the check ran, so its schedule and status advance.
    """
    if outcome.grouping is None:
        return outcome
    if outcome.grouping.splits_like(Grouping.from_stored(configuration.grouping)):
        return outcome
    return replace(outcome, groups=(), overflowed=0, overflow_is_lower_bound=False, evicted=(), held_delivery=None)


_HELD_BY_MUTE: Final = {
    AlertEventKind.FIRING: NotificationAction.FIRE.value,
    AlertEventKind.RESOLVED: NotificationAction.RESOLVE.value,
}


def _held_by_mute(
    configuration: PlatformAlertConfiguration, alert: PlatformAlert, group: GroupOutcome, now: datetime
) -> GroupOutcome:
    """The verdict, or the verdict muted when a mute that the check did not see holds now.

    A check reads the mute when it starts, so a snooze set while it runs reaches only this write.
    Held the way the machine holds a muted announcement: the state and the firing still move,
    and `last_notified_at` stays behind, so a held fire goes out once the mute ends.
    """
    held = _HELD_BY_MUTE.get(group.kind)
    snooze_until = _composed(configuration, alert).snooze_until
    if held is None or snooze_until is None or snooze_until <= now:
        return group
    return replace(group, kind=AlertEventKind.CHECK, notified=False, muted_notification=held)


def record_outcomes(team_id: int, outcomes: Sequence[PlatformAlertOutcome], now: datetime) -> int:
    """Persists a batch's decisions and advances each configuration's schedule.

    Two statements rather than two per alert, in one transaction, so a crash between them cannot
    leave an alert marked as notified while its schedule still says the check is due. The schedule
    advances the way the source's own stack advances it, sharded across the cadence so a fleet does
    not converge on one minute. A schedule restriction does not move it, because a restricted check
    still runs and only its announcement is held.

    Safe to run twice on the same batch. An attempt that commits leaves every configuration due
    after `now`, and a replay of that attempt skips those rows rather than advancing them a second
    time and skipping a cycle.
    Returns how many configurations it wrote, which is fewer than it was given when a replay
    finds rows an earlier attempt already advanced.

    History is written after the transaction commits, not inside it. A row the platform cannot
    record is a gap a comparison sees; a transaction that rolled back on a ClickHouse outage would
    instead leave the alert due with its state unwritten, which is worse.
    """
    if not outcomes:
        return 0
    by_id = {str(o.configuration_id): o for o in outcomes}

    with transaction.atomic():
        # Locked in a fixed order, so an ownership handover waits for this write or this write
        # re-reads the row after it and finds it no longer due.
        configurations = list(
            PlatformAlertConfiguration.objects.for_team(team_id)
            .select_for_update()
            .defer(*RULE_METADATA_FIELDS)
            .filter(id__in=by_id)
            .filter(due_q(now))
            .order_by("id")
        )
        if not configurations:
            return 0
        for configuration in configurations:
            by_id[str(configuration.id)] = _without_stale_groups(configuration, by_id[str(configuration.id)])
        # In outcome order, because the source put the groups it most wants kept first.
        returned = [
            _InstanceKey(configuration_id=str(configuration.id), grouping_key=group.grouping_key)
            for configuration in configurations
            for group in by_id[str(configuration.id)].groups
        ]
        healthy = [
            configuration
            for configuration in configurations
            if _check_status(configuration, by_id[str(configuration.id)]) == PlatformAlertConfiguration.CheckStatus.OK
        ]
        # Before the cap is counted, so a slot a stale or evicted group held is free for a new one this check.
        _reap(team_id, healthy, now, returned=frozenset(returned))
        _evict(team_id, healthy, by_id, now)
        alerts = _alerts_for_write(team_id, configurations, returned)
        touched: list[PlatformAlert] = []
        # One read for the batch. Every configuration in it belongs to this team, and a
        # calendar recurrence resolves its anchor against the team's zone.
        team_timezone = Team.objects.filter(id=team_id).values_list("timezone", flat=True).first() or "UTC"

        rows: list[PlatformAlertEventRow] = []
        holds: list[PlatformAlertDeliveryHold] = []
        for configuration in configurations:
            outcome = by_id[str(configuration.id)]
            hold = delivery_holds.hold_for(configuration, outcome, now)
            if hold is not None:
                holds.append(hold)
            turned_away = 0
            for reported in outcome.groups:
                alert = alerts.get(
                    _InstanceKey(configuration_id=str(configuration.id), grouping_key=reported.grouping_key)
                )
                if alert is None:
                    # `max_instances` fell after the source admitted this group, so it overflowed here instead.
                    turned_away += 1
                    continue
                group = _held_by_mute(configuration, alert, reported, now)
                touched.append(alert)
                alert.last_seen_at = now
                # A hashed key's group that a check did not return arrives without labels, and its
                # labels have not changed, so the stored ones stay.
                if group.labels:
                    alert.labels = group.labels
                # Before either row is mutated, so the history row keeps the state the check found.
                rows.append(
                    _event_row(
                        configuration,
                        outcome,
                        group,
                        alert=alert,
                        previous_state=_composed(configuration, alert).state,
                        now=now,
                    )
                )
                if group.notified:
                    alert.last_notified_at = now
                if group.new_state in _CHECK_STATUSES:
                    continue
                episode = group.firing_episode
                # The row holds the firing the alert is in, so a check that ended one clears it. The
                # ended firing stays on the history row instead.
                alert.firing_started_at = episode.started_at if episode and not episode.ended else None
                alert.state = group.new_state

            if outcome.failure is not None:
                # The empty-key row, so a failure row states the state an ungrouped check found.
                ungrouped = alerts.get(_InstanceKey(configuration_id=str(configuration.id), grouping_key=""))
                rows.append(
                    _event_row(
                        configuration,
                        outcome,
                        outcome.failure,
                        alert=None,
                        previous_state=_composed(configuration, ungrouped).state,
                        now=now,
                    )
                )
            configuration.check_status = _check_status(configuration, outcome)
            configuration.consecutive_failures = outcome.consecutive_failures
            if outcome.failure is None and not outcome.skipped:
                configuration.overflowed_groups = outcome.overflowed + turned_away
                configuration.overflow_is_lower_bound = outcome.overflow_is_lower_bound
            if outcome.disable:
                configuration.enabled = False
            configuration.next_check_at = advance_schedule(
                current_next_check_at=configuration.next_check_at,
                check_interval_minutes=configuration.check_interval_minutes,
                recurrence_unit=configuration.recurrence_unit,
                anchor_time=configuration.anchor_time,
                tz_name=team_timezone,
                now=now,
                configuration_id=configuration.id,
                shard_offset_seconds=_shard_offset_seconds(configuration, outcome),
                schedule_key=outcome.schedule_key,
                blocked_windows=parse_blocked_windows_tuples(configuration.schedule_restriction),
            )

        # Batched, because a grouped check writes a row per group rather than one per configuration.
        PlatformAlert.objects.for_team(team_id).bulk_update(
            touched, ["state", "last_notified_at", "firing_started_at", "last_seen_at", "labels"], batch_size=500
        )
        PlatformAlertConfiguration.objects.for_team(team_id).bulk_update(
            configurations,
            [
                "check_status",
                "consecutive_failures",
                "enabled",
                "next_check_at",
                "overflowed_groups",
                "overflow_is_lower_bound",
            ],
        )
        # In this transaction, because a recorded firing whose hold was lost would never be sent. A
        # conflict keeps the first hold, so a repeated evaluation key cannot fail every later record.
        PlatformAlertDeliveryHold.objects.for_team(team_id).bulk_create(holds, ignore_conflicts=True)
        # `on_commit` rather than a statement after the block, so a caller that wraps this in its
        # own `atomic()` cannot leave history for state its rollback removed.
        transaction.on_commit(lambda: record_history(team_id, rows))
    return len(configurations)


_CADENCE_FIELDS: Final = ("check_interval_minutes", "recurrence_unit", "anchor_time")
_REVIVE_FENCE: Final = timedelta(minutes=1)
_ADMISSION_LOCK_SQL: Final = {
    True: "SELECT pg_advisory_xact_lock(hashtext(%s))",
    False: "SELECT pg_advisory_xact_lock_shared(hashtext(%s))",
}


def upsert_configuration(upsert: PlatformAlertUpsert, *, revive: bool = False) -> bool:
    """Copies one source configuration in. Returns True when it created a row.

    A copy the platform owns is left as it is. Every edit writes both of its rows, and a caller here
    reads its source row without a lock, so its snapshot can predate such an edit.

    Keyed on the row it came from, so a second run updates rather than duplicates.

    `next_check_at` is copied into a new row, into a disabled copy, into a copy with no schedule
    yet, and into a copy whose cadence this run changes. Otherwise the platform owns its schedule: a source can park its own next
    check, for example at the end of quiet hours, and copying that would skip checks the platform
    still runs.

    The recurrence is checked here rather than where the schedule advances, because an
    unparseable unit or anchor raised there would fail a whole batch of unrelated checks.

    `revive` says the source alert was just created or turned back on, which resets the copy
    even when it stayed enabled, for example a BROKEN copy that discovery skips.
    """
    if upsert.recurrence_unit is not None:
        to_recurrence_interval(upsert.recurrence_unit)
    anchor_time = validate_and_normalize_schedule_start_time(upsert.anchor_time)

    with transaction.atomic():
        existing = (
            PlatformAlertConfiguration.objects.unscoped()
            .select_for_update()
            .filter(legacy_configuration_id=upsert.legacy_configuration_id)
            .values("enabled", "next_check_at", "owner", *_CADENCE_FIELDS)
            .first()
        )
        if existing is not None and existing["owner"] == PlatformAlertOwner.PLATFORM:
            return False
        defaults = {
            "team_id": upsert.team_id,
            "name": upsert.name,
            "enabled": upsert.enabled,
            "source_kind": upsert.source_kind.value,
            "source_config": upsert.source_config,
            "check_interval_minutes": upsert.check_interval_minutes,
            "recurrence_unit": upsert.recurrence_unit,
            "anchor_time": anchor_time,
            "evaluation_periods": upsert.evaluation_periods,
            "datapoints_to_alarm": upsert.datapoints_to_alarm,
            "cooldown_minutes": upsert.cooldown_minutes,
            "schedule_restriction": upsert.schedule_restriction,
            # Reached by a backfill run, which re-admits a copy an operator switched off.
            "switched_off_at": None,
            # A source's snooze mutes the whole alert. State is left alone because a muted alert
            # keeps tracking reality.
            "snooze_until": upsert.snooze_until,
        }
        if (
            existing is None
            or not existing["enabled"]
            or existing["next_check_at"] is None
            or any(existing[key] != defaults[key] for key in _CADENCE_FIELDS)
        ):
            defaults["next_check_at"] = upsert.next_check_at
        # A copy that comes back on starts clean, as a source's own enable does. The state it was
        # switched off in is stale, and a firing kept from then would end in a resolve for an
        # episode nobody was told about.
        revived = existing is not None and upsert.enabled and (revive or not existing["enabled"])
        if revived:
            defaults.update(_CLEAN_START)
            # After any check already running, so an outcome it read before the source came back
            # on, such as a stop, finds the row no longer due and records nothing.
            defaults["next_check_at"] = max(
                upsert.next_check_at or django_timezone.now(), django_timezone.now() + _REVIVE_FENCE
            )
        configuration, created = PlatformAlertConfiguration.objects.unscoped().update_or_create(
            legacy_configuration_id=upsert.legacy_configuration_id,
            defaults=defaults,
            create_defaults={**defaults, "grouping": upsert.grouping.to_stored()},
        )
        if revived:
            PlatformAlert.objects.for_team(upsert.team_id).filter(configuration=configuration).update(
                state=PlatformAlert.State.NOT_FIRING.value, firing_started_at=None
            )
    return created


# What one check found about its groups. It says nothing once the alert regroups or comes back on.
_NO_OVERFLOW: Final = {"overflowed_groups": 0, "overflow_is_lower_bound": False}
# The state an alert that comes back on starts from, whichever path turns it back on.
_CLEAN_START: Final = {
    "consecutive_failures": 0,
    "check_status": PlatformAlertConfiguration.CheckStatus.OK,
    **_NO_OVERFLOW,
}


def write_edit(
    configuration: PlatformAlertConfiguration,
    edit: PlatformAlertConfigurationEdit,
    *,
    regrouped: bool,
    now: datetime,
) -> None:
    """Writes an edit made through an API onto a configuration locked by the caller.

    Here rather than with the edit's validation, because it writes `enabled` and the failure state,
    which only this module changes.
    """
    if regrouped:
        # The old keys never come back from a check, so each old instance would resolve and
        # announce a recovery that did not happen. They go, threads included, without a message.
        PlatformAlert.objects.for_team(configuration.team_id, canonical=True).filter(
            configuration=configuration
        ).delete()
        PlatformAlertThread.objects.for_team(configuration.team_id, canonical=True).filter(
            configuration=configuration
        ).delete()
    update_fields = [
        "name",
        "enabled",
        "source_config",
        "grouping",
        "schedule_restriction",
        "evaluation_periods",
        "datapoints_to_alarm",
        "cooldown_minutes",
        "labels",
        "annotations",
        "updated_at",
    ]
    reenabled = edit.enabled and not configuration.enabled
    # An alert turned back on starts clean, as a revived copy does. A BROKEN one would otherwise stay
    # out of discovery for good.
    cleared = _CLEAN_START if reenabled else _NO_OVERFLOW if regrouped else {}
    for field, value in cleared.items():
        setattr(configuration, field, value)
    update_fields += list(cleared)
    if reenabled:
        configuration.next_check_at = now + _REVIVE_FENCE
        update_fields.append("next_check_at")
    _assign_edit(configuration, edit)
    configuration.save(update_fields=update_fields)


def create_native_configuration(
    *,
    team_id: int,
    source_kind: SourceKind,
    edit: PlatformAlertConfigurationEdit,
    check_interval_minutes: int,
    destinations_owner: PlatformAlertOwner,
    now: datetime,
) -> PlatformAlertConfiguration:
    """Creates an alert the platform owns from the start, for a kind whose source keeps no row for it."""
    configuration = PlatformAlertConfiguration(
        team_id=team_id,
        source_kind=source_kind.value,
        check_interval_minutes=check_interval_minutes,
        next_check_at=now,
        owner=PlatformAlertOwner.PLATFORM,
        destinations_owner=destinations_owner,
    )
    _assign_edit(configuration, edit)
    # The model's own save logs the creation.
    configuration.save()
    return configuration


def _assign_edit(configuration: PlatformAlertConfiguration, edit: PlatformAlertConfigurationEdit) -> None:
    configuration.name = edit.name
    configuration.enabled = edit.enabled
    configuration.source_config = edit.source_config
    configuration.grouping = edit.grouping.to_stored()
    configuration.schedule_restriction = edit.schedule_restriction
    configuration.evaluation_periods = edit.evaluation_periods
    configuration.datapoints_to_alarm = edit.datapoints_to_alarm
    configuration.cooldown_minutes = edit.cooldown_minutes
    configuration.labels = edit.labels
    configuration.annotations = edit.annotations


def end_firing_instances(configuration: PlatformAlertConfiguration, *, now: datetime) -> list[PlatformAlert]:
    """Moves every firing instance of a configuration locked by the caller to not firing, and returns
    them as they were.

    The next check moves past a fence, so a check already running finds the row no longer due and
    records nothing. Otherwise it would write back the firing this just ended, with no incident open.
    """
    instances = PlatformAlert.objects.for_team(configuration.team_id, canonical=True).filter(
        configuration=configuration, state=PlatformAlertState.FIRING
    )
    firing = list(instances)
    if firing:
        instances.update(state=PlatformAlertState.NOT_FIRING, firing_started_at=None)
        configuration.next_check_at = max(configuration.next_check_at or now, now + _REVIVE_FENCE)
        configuration.save(update_fields=["next_check_at"])
    return firing


def write_snooze(configuration: PlatformAlertConfiguration, snooze_until: datetime | None, *, now: datetime) -> None:
    """Sets or clears a configuration's mute from a source's API.

    A snooze defers the next check to its end, as the logs stack runs no check while snoozed. A mute
    alone holds only messages, and a breach that went on would open a new incident during the snooze.
    """
    next_check_at = configuration.next_check_at or now
    current = configuration.snooze_until
    if current is not None and current > now:
        # The stored due time is the current snooze's end, which the new snooze replaces. A fence an
        # edit set earlier in this transaction is at most this far out, so it holds.
        next_check_at = min(next_check_at, now + _REVIVE_FENCE)
    if snooze_until is not None and snooze_until > now:
        next_check_at = max(next_check_at, snooze_until)
    configuration.snooze_until = snooze_until
    configuration.next_check_at = next_check_at
    configuration.save(update_fields=["snooze_until", "next_check_at", "updated_at"])


def upsert_if_running(upsert: PlatformAlertUpsert, *, revive: bool = False) -> None:
    """Copies one configuration in when its team already runs that source here.

    A copy the platform owns gets nothing, because every edit already writes both of its rows.
    Otherwise a team runs a source here while any of its parallel-run copies of that source is
    enabled. A team the backfill left out of its sample, or one
    `disable_configurations` switched off, gets nothing, and neither does a copy an operator switched
    off by name, so a write in the source never widens a sample or undoes an operator's switch-off.
    """
    with transaction.atomic():
        _hold_admission(upsert.source_kind.value, exclusive=False)
        team_copies = PlatformAlertConfiguration.objects.for_team(upsert.team_id).filter(
            source_kind=upsert.source_kind.value
        )
        existing = team_copies.filter(legacy_configuration_id=upsert.legacy_configuration_id).first()
        if existing is not None and existing.owner == PlatformAlertOwner.PLATFORM:
            return
        running = team_copies.filter(owner=PlatformAlertOwner.SOURCE, enabled=True).exists()
        switched_off = existing is not None and existing.switched_off_at is not None
        if running and not switched_off:
            upsert_configuration(upsert, revive=revive)


def _hold_admission(source_kind: str, *, exclusive: bool) -> None:
    """Orders admitting a copy against an operator's switch-off, so neither reads the other half done.

    An admission shares the lock, so admissions never wait on each other. A switch-off takes it
    alone, so it waits for admissions in flight and a later admission sees the copies off.
    """
    with connection.cursor() as cursor:
        cursor.execute(_ADMISSION_LOCK_SQL[exclusive], [f"alerts-platform-admission:{source_kind}"])


def refresh_settings(team_id: int, configuration_id: UUID, upsert: PlatformAlertUpsert) -> None:
    """Writes a source's current settings onto its copy, so history and messages state what a check
    evaluated.

    Settings only. The due time, `enabled` and the alert rows stay as they are, so an evaluation can
    call this before it decides and a retried attempt still finds the same checks due. A changed
    cadence takes effect from the next due time the check advances to.

    Raises `ValueError` on a cadence `upsert_configuration` would refuse, because a stored one that
    cannot advance fails every outcome of the batch it is recorded in.
    """
    if upsert.recurrence_unit is not None:
        to_recurrence_interval(upsert.recurrence_unit)
    anchor_time = validate_and_normalize_schedule_start_time(upsert.anchor_time)
    PlatformAlertConfiguration.objects.for_team(team_id).filter(id=configuration_id).update(
        name=upsert.name,
        source_config=upsert.source_config,
        check_interval_minutes=upsert.check_interval_minutes,
        recurrence_unit=upsert.recurrence_unit,
        anchor_time=anchor_time,
        evaluation_periods=upsert.evaluation_periods,
        datapoints_to_alarm=upsert.datapoints_to_alarm,
        cooldown_minutes=upsert.cooldown_minutes,
        schedule_restriction=upsert.schedule_restriction,
        # `update()` skips `auto_now`.
        updated_at=django_timezone.now(),
    )


_HANDOVER_FENCE: Final = timedelta(minutes=1)


# Longer than a delivery workflow can wait between the check that starts a firing and the first
# thread claim. Inside it, a firing with no claimed thread may still have a delivery on its way.
_DELIVERY_FENCE: Final = timedelta(minutes=10)


def _delivered_firing(
    team_id: int, configuration: PlatformAlertConfiguration, alerts: Sequence[PlatformAlert], *, at: datetime
) -> bool:
    """Whether any of these instances is inside a firing the platform delivered, or may still deliver.

    Every native send claims a thread keyed on the firing's start, so a firing with no claimed
    thread was never sent, once its delivery had time to start. A firing with an unknown start has
    no key to find, so it counts as sent.
    """
    started: list[PlatformAlert] = []
    for instance in alerts:
        if instance.firing_started_at is None:
            if instance.state == PlatformAlertState.FIRING:
                return True
        elif instance.firing_started_at > at - _DELIVERY_FENCE:
            return True
        else:
            started.append(instance)
    if not started:
        return False
    delivered = Q()
    for instance in started:
        delivered |= Q(grouping_key=instance.grouping_key, episode_started_at=instance.firing_started_at)
    return PlatformAlertThread.objects.for_team(team_id).filter(delivered, configuration=configuration).exists()


def take_ownership(handover: PlatformOwnershipHandover) -> bool:
    """Makes the platform the owner of a copied alert, carrying on from the source's state.

    The second writer of an alert's state beside `record_outcomes`. The caller holds the source's
    row lock and writes the source's owner in the same transaction, so both rows change together.
    Returns False, changing nothing, when the copy is inside a firing of its own that the platform
    delivered: a team on live delivery can have one open while its source is quiet, and replacing it
    would orphan the incident. A firing the platform never delivered opened nothing, so the source's
    state replaces it.
    A grouped copy carries only the configuration's fields. Its source holds one state for the whole
    alert, which no group inherits, and each group's row comes from the check that finds it.
    A firing carries over with its start unknown, the state of a firing that began before the
    platform recorded starts, so its resolve addresses the incident the source opened.
    Raises `PlatformAlertConfiguration.DoesNotExist` when the alert was never copied, and `ValueError`
    for a snooze, which the platform carries as a mute rather than a state, or for a firing of a
    grouped copy, which has no single group to carry it to. Only a platform-owned copy is grouped.
    """
    if handover.state == PlatformAlertState.SNOOZED:
        raise ValueError("a snoozed alert is handed over with its snooze, not in a snoozed state")
    with transaction.atomic():
        configuration = (
            PlatformAlertConfiguration.objects.for_team(handover.team_id)
            .select_for_update()
            .get(legacy_configuration_id=handover.legacy_configuration_id)
        )
        alert: PlatformAlert | None = None
        if Grouping.from_stored(configuration.grouping).mode == GroupingMode.SINGLE:
            key = _InstanceKey(configuration_id=str(configuration.id), grouping_key="")
            alert = _alerts_for_write(handover.team_id, [configuration], [key])[key]
            alerts = [alert]
        else:
            if handover.state == PlatformAlertState.FIRING:
                raise ValueError("a grouped copy has no single group to carry a firing to")
            # No grouped check writes the empty key, so a row for it would only hold a slot of the cap.
            alerts = _instances_by_configuration(handover.team_id, [configuration]).get(str(configuration.id), [])
        # A failing check status means the machine already ended the firing the row still holds.
        if configuration.check_status == PlatformAlertConfiguration.CheckStatus.OK and _delivered_firing(
            handover.team_id, configuration, alerts, at=handover.at
        ):
            return False
        # ERRORED and BROKEN are the configuration's check status, so the instance starts at rest.
        failing = handover.state in (PlatformAlertState.ERRORED, PlatformAlertState.BROKEN)
        configuration.check_status = (
            handover.state.value if failing else PlatformAlertConfiguration.CheckStatus.OK.value
        )
        configuration.owner = PlatformAlertOwner.PLATFORM
        configuration.owner_changed_at = handover.at
        configuration.consecutive_failures = handover.consecutive_failures
        # A platform check that started before the handover records only rows still due, so a
        # schedule after the handover keeps it from recording over the carried state.
        configuration.next_check_at = max(handover.next_check_at, handover.at + _HANDOVER_FENCE)
        configuration.save(
            update_fields=["owner", "owner_changed_at", "consecutive_failures", "next_check_at", "check_status"]
        )

        if alert is not None:
            alert.state = PlatformAlertState.NOT_FIRING if failing else handover.state
            alert.firing_started_at = None
            alert.last_notified_at = handover.last_notified_at
            alert.save(update_fields=["state", "firing_started_at", "last_notified_at"])
    return True


def give_back_ownership(
    *, team_id: int, legacy_configuration_id: UUID, at: datetime, source_runs_calendar_schedules: bool = False
) -> PlatformHandback | HandbackRefusal:
    """Hands a copied alert back to its source, or says why the platform keeps it.

    A source that runs calendar schedules itself takes back an alert on one. Any other source gets
    only interval cadences back.

    The caller holds the source's row lock and writes the source's owner and state in the same
    transaction. Raises `PlatformAlertConfiguration.DoesNotExist` when the alert was never copied,
    and `ValueError` when the platform does not own it, because both owners change together.
    """
    with transaction.atomic():
        configurations = PlatformAlertConfiguration.objects.for_team(team_id).select_for_update()
        configuration = configurations.get(legacy_configuration_id=legacy_configuration_id)
        if configuration.owner != PlatformAlertOwner.PLATFORM:
            raise ValueError("the platform does not own this alert, so its owner disagrees with its source's")
        alerts = list(PlatformAlert.objects.for_team(team_id).filter(configuration=configuration))
        calendar = configuration.recurrence_unit is not None and not source_runs_calendar_schedules
        # A grouped copy with no group open yet still splits its results, which its source cannot do.
        if (
            calendar
            or Grouping.from_stored(configuration.grouping).mode != GroupingMode.SINGLE
            or any(alert.grouping_key for alert in alerts)
        ):
            return HandbackRefusal.NOT_PORTABLE
        alert = alerts[0] if alerts else None
        if alert is not None and (alert.state == PlatformAlertState.FIRING or alert.firing_started_at is not None):
            return HandbackRefusal.FIRING
        # The same rule discovery reads, so an alert discovery skips is never waited on. A check
        # advances `next_check_at` when it records, so a row not due under this lock has no
        # platform check between reading the alert and recording it.
        if configurations.filter(pk=configuration.pk, enabled=True).filter(due_q(at)).exclude(suppressed()).exists():
            return HandbackRefusal.CHECK_DUE

        handback = PlatformHandback(
            state=PlatformAlertState(_composed(configuration, alert).state),
            last_notified_at=alert.last_notified_at if alert is not None else None,
            consecutive_failures=configuration.consecutive_failures,
            next_check_at=configuration.next_check_at,
            enabled=configuration.enabled,
        )
        configuration.owner = PlatformAlertOwner.SOURCE
        configuration.owner_changed_at = at
        # A check can still be running for a copy that is disabled or not due, and it records only
        # rows still due, so this keeps it from recording and delivering after the handback.
        configuration.next_check_at = max(configuration.next_check_at or at, at + _HANDOVER_FENCE)
        configuration.save(update_fields=["owner", "owner_changed_at", "next_check_at"])
        return handback


def reset_broken(*, team_id: int, legacy_configuration_id: UUID, at: datetime) -> int | None:
    """Clears a broken alert the platform owns so the next tick checks it again, from rest.

    Returns the failure count it cleared, or None when the alert is not broken. Discovery skips a
    broken alert, so without this it never runs again. The caller holds the source's row lock.
    """
    with transaction.atomic():
        configuration = (
            PlatformAlertConfiguration.objects.for_team(team_id)
            .select_for_update()
            .get(legacy_configuration_id=legacy_configuration_id)
        )
        if configuration.owner != PlatformAlertOwner.PLATFORM:
            raise ValueError("the platform does not own this alert, so its source resets it")
        if configuration.check_status != PlatformAlertConfiguration.CheckStatus.BROKEN:
            return None
        cleared = configuration.consecutive_failures
        configuration.check_status = PlatformAlertConfiguration.CheckStatus.OK
        configuration.consecutive_failures = 0
        configuration.next_check_at = at
        configuration.save(update_fields=["check_status", "consecutive_failures", "next_check_at"])
        # A failed check keeps a firing so a recovery continues it. A reset starts clean instead, or
        # the next breach would find the old episode open and announce nothing.
        PlatformAlert.objects.for_team(team_id).filter(configuration=configuration).update(
            state=PlatformAlertState.NOT_FIRING.value, firing_started_at=None
        )
    return cleared


def disable_configurations(
    source_kind: str, *, team_id: int | None = None, legacy_configuration_ids: Collection[UUID] | None = None
) -> int:
    """Switches off a source's parallel-run copies, or one team's, or the copies of named source
    alerts, and returns how many it switched off.

    Rows, state and history stay, so a comparison can still read what ran. Discovery and the batch
    read both skip a disabled row, so no new check starts after this. Checks already running finish.
    """
    with transaction.atomic():
        _hold_admission(source_kind, exclusive=True)
        # Cross-team on purpose, for an operator stopping a whole source at once. Only copies the
        # source still owns: once the platform owns an alert, its copy is the production alert, and
        # switching it off would silence real notifications rather than stop a parallel check.
        rows = PlatformAlertConfiguration.objects.unscoped().filter(
            source_kind=source_kind, enabled=True, owner=PlatformAlertOwner.SOURCE
        )
        if team_id is not None:
            rows = rows.filter(team_id=team_id)
        if legacy_configuration_ids is not None:
            rows = rows.filter(legacy_configuration_id__in=legacy_configuration_ids)
        return rows.update(enabled=False, switched_off_at=django_timezone.now())
