"""Reads and writes for the skeleton shared alert tables.

A source decides whether its data breached; everything about what that means for the alert,
and every write to these rows, stays here. A source never holds one of these models.
"""

from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from django.db import transaction
from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts_platform.backend.facade.contracts import (
    CheckFailure,
    Grouping,
    GroupingMode,
    GroupOutcome,
    InstanceCheckState,
    PlatformAlertCheckInput,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
    source_condition,
)
from products.alerts_platform.backend.facade.platform_metrics import (
    increment_groups_over_cap,
    increment_history_rows_dropped,
    increment_instances_reaped,
    safe_record,
)
from products.alerts_platform.backend.facade.scheduling import (
    advance_schedule,
    compute_shard_offset_seconds,
    to_recurrence_interval,
    validate_and_normalize_schedule_start_time,
)
from products.alerts_platform.backend.logic.platform_alert_events import PlatformAlertEventRow, insert_events
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration


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


# Long enough that a group which resolves and fires again inside a day keeps its cooldown.
REAP_AFTER: Final = timedelta(hours=24)


def _reap(team_id: int, configurations: Sequence[PlatformAlertConfiguration], now: datetime) -> None:
    """Deletes instances that hold a slot and nothing else, so a stale group frees its place.

    Only an instance that is not firing, not muted, and that no check returned for longer than both
    `REAP_AFTER` and its cooldown. A configuration whose checks fail returns no groups, so its
    instances look unseen without being gone, and none of them is reaped while it is not OK.
    """
    # An ungrouped configuration's one instance is returned by every check, so it has nothing to reap.
    healthy = {
        str(c.id): c
        for c in configurations
        if c.check_status == PlatformAlertConfiguration.CheckStatus.OK
        and Grouping.from_stored(c.grouping).mode != GroupingMode.SINGLE
    }
    if not healthy:
        return
    candidates = (
        PlatformAlert.objects.for_team(team_id)
        .filter(
            configuration_id__in=list(healthy), state=PlatformAlert.State.NOT_FIRING, last_seen_at__lt=now - REAP_AFTER
        )
        .filter(Q(snooze_until__isnull=True) | Q(snooze_until__lte=now))
        .values_list("id", "configuration_id", "last_seen_at")
    )
    reaped: dict[str, list[UUID]] = {}
    for alert_id, configuration_id, last_seen_at in candidates:
        configuration = healthy[str(configuration_id)]
        if configuration.snooze_until is not None and configuration.snooze_until > now:
            continue
        if last_seen_at is None or last_seen_at >= now - timedelta(minutes=configuration.cooldown_minutes):
            continue
        reaped.setdefault(configuration.source_kind, []).append(alert_id)
    for source_kind, ids in reaped.items():
        PlatformAlert.objects.for_team(team_id).filter(id__in=ids).delete()
        safe_record(increment_instances_reaped, source_kind, len(ids))


def suppressed() -> Q:
    """Configurations a check status holds back.

    BROKEN only. A mute holds an announcement rather than a check, so a snoozed alert is
    discovered and evaluated like any other and its state keeps tracking reality.

    Discovery and the batch read both reach for this rather than each writing the predicate out.
    If the two disagreed, a broken alert would be dispatched by one and dropped by the other,
    every tick, in silence.
    """
    return Q(check_status=PlatformAlertConfiguration.CheckStatus.BROKEN)


def due_checks(
    team_id: int, source_kind: str, slot: str, cutoff: datetime, *, configuration_ids: Collection[str] | None = None
) -> tuple[PlatformAlertCheckInput, ...]:
    """Every configuration in one batch key, with its runtime state, ready to evaluate.

    `configuration_ids` narrows the batch to those rows, for a source that evaluates one check at
    a time and must still read nothing the batch would not.
    """
    due = (
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(enabled=True, source_kind=source_kind)
        .filter(due_q(cutoff))
        .exclude(suppressed())
    )
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
    evaluation-time by convention rather than by construction: `upsert_configuration`, reached
    only through a hand-run backfill command, and only for a configuration already copied whose
    source row changed since. The row then states the new condition beside a verdict measured
    against the old one. Carry the snapshot on the outcome if that stops being acceptable.

    The source's bound is flattened in beside the platform's own fields, so a reader finds it at
    the top level whatever shape the source gives it.
    """
    return {
        **source_condition(configuration.source_config),
        "evaluation_periods": configuration.evaluation_periods,
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
    return PlatformAlertEventRow(
        team_id=configuration.team_id,
        configuration_id=configuration.id,
        alert_id=alert.id if alert else CONFIGURATION_ROW_ALERT_ID,
        grouping_key=alert.grouping_key if alert else "",
        evaluation_key=outcome.evaluation_key,
        kind=verdict.kind.value,
        alert_name=configuration.name,
        previous_state=previous_state,
        state=verdict.new_state,
        # The whole episode, ended or not. A resolve names the firing it closed, which is what a
        # thread key needs and what the alert row no longer holds.
        episode_started_at=verdict.firing_episode.started_at if verdict.firing_episode else None,
        value=group.value if group else None,
        labels=group.labels if group else {},
        condition_snapshot=_condition_snapshot(configuration),
        source_config_snapshot=configuration.source_config,
        query_duration_ms=outcome.query_duration_ms,
        error_message=outcome.error_message,
        consecutive_failures=outcome.consecutive_failures,
        muted_notification=verdict.muted_notification,
        occurred_at=now,
    )


def _record_history(team_id: int, rows: Sequence[PlatformAlertEventRow]) -> None:
    recorded = insert_events(team_id, rows)
    if recorded < len(rows):
        safe_record(increment_history_rows_dropped, len(rows) - recorded)


_CHECK_STATUSES: Final = frozenset(
    {PlatformAlertConfiguration.CheckStatus.ERRORED.value, PlatformAlertConfiguration.CheckStatus.BROKEN.value}
)


def _check_status(configuration: PlatformAlertConfiguration, outcome: PlatformAlertOutcome) -> str:
    """BROKEN over ERRORED over OK, because a check is as bad as its worst verdict.

    A failure that the policy rides through leaves the status where it was, so only the machine's
    ERRORED or BROKEN moves it.
    """
    if outcome.failure is not None:
        failed = outcome.failure.new_state
        return failed if failed in _CHECK_STATUSES else configuration.check_status
    states = {group.new_state for group in outcome.groups}
    for status in (PlatformAlertConfiguration.CheckStatus.BROKEN, PlatformAlertConfiguration.CheckStatus.ERRORED):
        if status.value in states:
            return status.value
    return PlatformAlertConfiguration.CheckStatus.OK.value


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
        configurations = list(
            PlatformAlertConfiguration.objects.for_team(team_id).filter(id__in=by_id).filter(due_q(now))
        )
        if not configurations:
            return 0
        alerts = _alerts_for_write(
            team_id,
            configurations,
            [
                _InstanceKey(configuration_id=str(configuration.id), grouping_key=group.grouping_key)
                for configuration in configurations
                for group in by_id[str(configuration.id)].groups
            ],
        )
        touched: list[PlatformAlert] = []
        # One read for the batch. Every configuration in it belongs to this team, and a
        # calendar recurrence resolves its anchor against the team's zone.
        team_timezone = Team.objects.filter(id=team_id).values_list("timezone", flat=True).first() or "UTC"

        rows: list[PlatformAlertEventRow] = []
        for configuration in configurations:
            outcome = by_id[str(configuration.id)]
            for group in outcome.groups:
                alert = alerts.get(
                    _InstanceKey(configuration_id=str(configuration.id), grouping_key=group.grouping_key)
                )
                if alert is None:
                    continue
                touched.append(alert)
                alert.last_seen_at = now
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
                shard_offset_seconds=compute_shard_offset_seconds(
                    configuration.id, configuration.check_interval_minutes
                ),
            )

        # Batched, because a grouped check writes a row per group rather than one per configuration.
        PlatformAlert.objects.for_team(team_id).bulk_update(
            touched, ["state", "last_notified_at", "firing_started_at", "last_seen_at"], batch_size=500
        )
        PlatformAlertConfiguration.objects.for_team(team_id).bulk_update(
            configurations, ["check_status", "consecutive_failures", "enabled", "next_check_at"]
        )
        _reap(team_id, configurations, now)
        # `on_commit` rather than a statement after the block, so a caller that wraps this in its
        # own `atomic()` cannot leave history for state its rollback removed.
        transaction.on_commit(lambda: _record_history(team_id, rows))
    return len(configurations)


_CADENCE_FIELDS: Final = ("check_interval_minutes", "recurrence_unit", "anchor_time")


def upsert_configuration(upsert: PlatformAlertUpsert) -> bool:
    """Copies one source configuration in. Returns True when it created a row.

    Keyed on the row it came from, so a second run updates rather than duplicates.

    `next_check_at` is copied into a new row, into a disabled copy, into a copy with no schedule
    yet, and into a copy whose cadence this run changes. Otherwise the platform owns its schedule: a source can park its own next
    check, for example at the end of quiet hours, and copying that would skip checks the platform
    still runs.

    The recurrence is checked here rather than where the schedule advances, because an
    unparseable unit or anchor raised there would fail a whole batch of unrelated checks.
    """
    if upsert.recurrence_unit is not None:
        to_recurrence_interval(upsert.recurrence_unit)
    anchor_time = validate_and_normalize_schedule_start_time(upsert.anchor_time)

    with transaction.atomic():
        existing = (
            PlatformAlertConfiguration.objects.unscoped()
            .select_for_update()
            .filter(legacy_configuration_id=upsert.legacy_configuration_id)
            .values("enabled", "next_check_at", *_CADENCE_FIELDS)
            .first()
        )
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
        configuration, created = PlatformAlertConfiguration.objects.unscoped().update_or_create(
            legacy_configuration_id=upsert.legacy_configuration_id, defaults=defaults
        )
    return created


def disable_configurations(source_kind: str, *, team_id: int | None = None) -> int:
    """Switches off a source's copies, or one team's, and returns how many it switched off.

    Rows, state and history stay, so a comparison can still read what ran. Discovery and the batch
    read both skip a disabled row, so no new check starts after this. Checks already running finish.
    """
    # Cross-team on purpose, for an operator stopping a whole source at once.
    rows = PlatformAlertConfiguration.objects.unscoped().filter(source_kind=source_kind, enabled=True)
    if team_id is not None:
        rows = rows.filter(team_id=team_id)
    return rows.update(enabled=False)
