"""Reads and writes for the skeleton shared alert tables.

A source decides whether its data breached; everything about what that means for the alert,
and every write to these rows, stays here. A source never holds one of these models.
"""

from collections.abc import Sequence
from datetime import datetime

from django.db import transaction
from django.db.models import Exists, OuterRef, Q

from products.alerts.backend.facade.conditions import compile_alert_condition
from products.alerts.backend.facade.contracts import (
    PlatformAlertCheckInput,
    PlatformAlertGroupState,
    PlatformAlertOutcome,
    PlatformAlertUpsert,
)
from products.alerts.backend.facade.scheduling import advance_next_check_at, compute_shard_offset_seconds
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration


def due_q(moment: datetime) -> Q:
    """Configurations a check is owed at `moment`. The read and the write share it, because the
    write skips a row already advanced past it and that is what makes a replay safe."""
    return Q(next_check_at__lte=moment) | Q(next_check_at__isnull=True)


GroupedAlerts = dict[str, dict[str, PlatformAlert]]


def _existing_alerts(team_id: int, configurations: Sequence[PlatformAlertConfiguration]) -> GroupedAlerts:
    """The runtime rows that exist, by configuration and then by grouping key.

    A configuration with no rows has never been evaluated. An ungrouped source has one row with an
    empty key; a grouped source has one row per label set it has seen.
    """
    grouped: GroupedAlerts = {}
    for alert in PlatformAlert.objects.for_team(team_id).filter(configuration__in=configurations):
        grouped.setdefault(str(alert.configuration_id), {})[alert.grouping_key] = alert
    return grouped


def _alerts_for_write(
    team_id: int,
    configurations: Sequence[PlatformAlertConfiguration],
    keys_by_configuration: dict[str, set[str]] | None = None,
) -> GroupedAlerts:
    """The runtime rows, creating any (configuration, grouping key) that has none yet.

    Without `keys_by_configuration` every configuration gets its root row, which is what an
    ungrouped source and the copy-in need.
    """
    existing = _existing_alerts(team_id, configurations)
    missing: list[PlatformAlert] = []
    for configuration in configurations:
        wanted = (keys_by_configuration or {}).get(str(configuration.id), {""})
        present = existing.get(str(configuration.id), {})
        missing.extend(
            PlatformAlert(team_id=team_id, configuration=configuration, grouping_key=key)
            for key in wanted
            if key not in present
        )
    if missing:
        # ignore_conflicts leans on the unique constraint, so a concurrent cycle creating the
        # same row is not an error. `for_team` because these models are fail-closed and a
        # Temporal activity has no ambient scope; the rows still carry `team_id` themselves,
        # because a queryset filter does not propagate into row creation.
        PlatformAlert.objects.for_team(team_id).bulk_create(missing, ignore_conflicts=True)
        existing = _existing_alerts(team_id, configurations)
    return existing


def suppressed() -> Exists:
    """Configurations a runtime state holds back.

    BROKEN only. A mute holds an announcement rather than a check, so a snoozed alert is
    discovered and evaluated like any other and its state keeps tracking reality.

    The state lives on `PlatformAlert`, so discovery and the batch read both reach for this
    rather than each writing the predicate out. If the two disagreed, a broken alert would be
    dispatched by one and dropped by the other, every tick, in silence.

    Excluded as one `Exists` rather than as a lookup across the relation. Django splits an
    excluded multi-valued lookup into a subquery per leaf, which lets the conditions match
    different alert rows once a source writes a real grouping key, and buries them where
    Postgres cannot lift them into an anti-join.
    """
    # `unscoped` because the subquery runs without ambient scope in both callers, and it is
    # correlated to a configuration the outer query has already scoped, so the foreign key keeps
    # it inside that team.
    return Exists(
        PlatformAlert.objects.unscoped().filter(
            configuration=OuterRef("pk"), grouping_key="", state=PlatformAlert.State.BROKEN
        )
    )


def due_checks(team_id: int, source_kind: str, slot: str, cutoff: datetime) -> tuple[PlatformAlertCheckInput, ...]:
    """Every configuration in one batch key, with its runtime state, ready to evaluate."""
    configurations = list(
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(enabled=True, source_kind=source_kind)
        .filter(due_q(cutoff))
        .exclude(suppressed())
        # Ordered so a retried attempt keeps the same alerts under any downstream cap.
        .order_by("id")
    )
    configurations = [c for c in configurations if slot_of(c.next_check_at, cutoff) == slot]
    if not configurations:
        return ()

    alerts = _existing_alerts(team_id, configurations)
    return tuple(_check(c, alerts.get(str(c.id), {})) for c in configurations)


def _group_state(alert: PlatformAlert) -> PlatformAlertGroupState:
    return PlatformAlertGroupState(
        grouping_key=alert.grouping_key,
        state=alert.state,
        last_notified_at=alert.last_notified_at,
        snooze_until=alert.snooze_until,
    )


def _check(c: PlatformAlertConfiguration, alerts: dict[str, PlatformAlert]) -> PlatformAlertCheckInput:
    root = alerts.get("")
    return PlatformAlertCheckInput(
        id=c.id,
        team_id=c.team_id,
        name=c.name,
        source_config=c.source_config,
        threshold_count=c.threshold_count,
        threshold_operator=c.threshold_operator,
        window_minutes=c.window_minutes,
        check_interval_minutes=c.check_interval_minutes,
        evaluation_periods=c.evaluation_periods,
        datapoints_to_alarm=c.datapoints_to_alarm,
        cooldown_minutes=c.cooldown_minutes,
        schedule_restriction=c.schedule_restriction,
        next_check_at=c.next_check_at,
        consecutive_failures=c.consecutive_failures,
        legacy_configuration_id=c.legacy_configuration_id,
        state=root.state if root else PlatformAlert.State.NOT_FIRING.value,
        last_notified_at=root.last_notified_at if root else None,
        snooze_until=root.snooze_until if root else None,
        groups=tuple(_group_state(alert) for key, alert in sorted(alerts.items())),
        condition_type=c.condition_type,
        condition_bytecode=c.condition_bytecode,
    )


def slot_of(next_check_at: datetime | None, cutoff: datetime) -> str:
    """The minute a configuration is due for. One that has never been checked has no due time
    of its own, so it belongs to the tick that found it.

    The single definition: discovery mints a key with it and this filters rows back down to
    one. If the two ever disagreed, every alert would evaluate nothing, silently.
    """
    return (next_check_at or cutoff).replace(second=0, microsecond=0).isoformat()


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
    """
    if not outcomes:
        return 0
    by_configuration: dict[str, list[PlatformAlertOutcome]] = {}
    for outcome in outcomes:
        by_configuration.setdefault(str(outcome.configuration_id), []).append(outcome)

    with transaction.atomic():
        configurations = list(
            PlatformAlertConfiguration.objects.for_team(team_id).filter(id__in=by_configuration).filter(due_q(now))
        )
        if not configurations:
            return 0
        keys = {str(c.id): {outcome.grouping_key for outcome in by_configuration[str(c.id)]} for c in configurations}
        alerts = _alerts_for_write(team_id, configurations, keys)

        written: list[PlatformAlert] = []
        retired: list[PlatformAlert] = []
        for configuration in configurations:
            group_outcomes = by_configuration[str(configuration.id)]
            for outcome in group_outcomes:
                alert = alerts[str(configuration.id)][outcome.grouping_key]
                if outcome.retire and outcome.grouping_key:
                    # A label set the query no longer returns and that holds nothing. The root row
                    # is never retired: it carries the configuration's own state.
                    retired.append(alert)
                    continue
                alert.state = outcome.new_state
                if outcome.notified:
                    alert.last_notified_at = now
                written.append(alert)

            # Evaluation-level state: a failed check fails the whole evaluation, so the worst
            # group decides the counter and any group can disable the configuration.
            configuration.consecutive_failures = max(o.consecutive_failures for o in group_outcomes)
            if any(o.disable for o in group_outcomes):
                configuration.enabled = False
            configuration.next_check_at = advance_next_check_at(
                configuration.next_check_at,
                configuration.check_interval_minutes,
                now,
                shard_offset_seconds=compute_shard_offset_seconds(
                    configuration.id, configuration.check_interval_minutes
                ),
            )

        PlatformAlert.objects.for_team(team_id).bulk_update(written, ["state", "last_notified_at"])
        if retired:
            PlatformAlert.objects.for_team(team_id).filter(id__in=[alert.id for alert in retired]).delete()
        PlatformAlertConfiguration.objects.for_team(team_id).bulk_update(
            configurations, ["consecutive_failures", "enabled", "next_check_at"]
        )
        return len(configurations)


def upsert_configuration(upsert: PlatformAlertUpsert) -> bool:
    """Copies one source configuration in. Returns True when it created a row.

    Keyed on the row it came from, so a second run updates rather than duplicates.
    """
    # Compiled before the transaction: a program that cannot run is refused and nothing is written.
    bytecode = compile_alert_condition(upsert.condition_source or "") if upsert.condition_type == "hog" else None
    with transaction.atomic():
        configuration, created = PlatformAlertConfiguration.objects.unscoped().update_or_create(
            legacy_configuration_id=upsert.legacy_configuration_id,
            defaults={
                "team_id": upsert.team_id,
                "name": upsert.name,
                "enabled": upsert.enabled,
                "source_kind": upsert.source_kind.value,
                "source_config": upsert.source_config,
                "threshold_count": upsert.threshold_count,
                "threshold_operator": upsert.threshold_operator,
                "window_minutes": upsert.window_minutes,
                "check_interval_minutes": upsert.check_interval_minutes,
                "evaluation_periods": upsert.evaluation_periods,
                "datapoints_to_alarm": upsert.datapoints_to_alarm,
                "cooldown_minutes": upsert.cooldown_minutes,
                "schedule_restriction": upsert.schedule_restriction,
                "next_check_at": upsert.next_check_at,
                "condition_type": upsert.condition_type,
                "condition_source": upsert.condition_source,
                "condition_bytecode": bytecode,
            },
        )
        alert = _alerts_for_write(upsert.team_id, [configuration])[str(configuration.id)][""]
        # State is left alone because a muted alert keeps tracking reality.
        alert.snooze_until = upsert.snooze_until
        alert.save(update_fields=["snooze_until"])
    return created
