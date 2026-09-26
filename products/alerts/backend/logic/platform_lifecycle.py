"""Reads and writes for the skeleton shared alert tables.

A source decides whether its data breached; everything about what that means for the alert,
and every write to these rows, stays here. A source never holds one of these models.
"""

from collections.abc import Sequence
from datetime import datetime

from django.db import transaction
from django.db.models import Exists, OuterRef, Q

from products.alerts.backend.facade.contracts import PlatformAlertCheckInput, PlatformAlertOutcome, PlatformAlertUpsert
from products.alerts.backend.facade.platform_metrics import increment_history_rows_dropped, safe_record
from products.alerts.backend.facade.scheduling import advance_next_check_at, compute_shard_offset_seconds
from products.alerts.backend.logic.platform_alert_events import PlatformAlertEventRow, insert_events
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration


def due_q(moment: datetime) -> Q:
    """Configurations a check is owed at `moment`. The read and the write share it, because the
    write skips a row already advanced past it and that is what makes a replay safe."""
    return Q(next_check_at__lte=moment) | Q(next_check_at__isnull=True)


def _existing_alerts(team_id: int, configurations: Sequence[PlatformAlertConfiguration]) -> dict[str, PlatformAlert]:
    """The runtime rows that exist. A configuration with none has never been evaluated.

    The grouping key is empty until a source groups its results, so today this is the whole of
    an alert's state and a real key needs no new table.
    """
    return {
        str(alert.configuration_id): alert
        for alert in PlatformAlert.objects.for_team(team_id).filter(configuration__in=configurations, grouping_key="")
    }


def _alerts_for_write(team_id: int, configurations: Sequence[PlatformAlertConfiguration]) -> dict[str, PlatformAlert]:
    """The runtime rows, creating any configuration that has none yet."""
    existing = _existing_alerts(team_id, configurations)
    missing = [c for c in configurations if str(c.id) not in existing]
    if missing:
        # ignore_conflicts leans on the unique constraint, so a concurrent cycle creating the
        # same row is not an error. `for_team` because these models are fail-closed and a
        # Temporal activity has no ambient scope; the rows still carry `team_id` themselves,
        # because a queryset filter does not propagate into row creation.
        PlatformAlert.objects.for_team(team_id).bulk_create(
            [PlatformAlert(team_id=team_id, configuration=c, grouping_key="") for c in missing],
            ignore_conflicts=True,
        )
        existing.update(_existing_alerts(team_id, missing))
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
    return tuple(_check(c, alerts.get(str(c.id))) for c in configurations)


def _check(c: PlatformAlertConfiguration, alert: PlatformAlert | None) -> PlatformAlertCheckInput:
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
        state=alert.state if alert else PlatformAlert.State.NOT_FIRING.value,
        last_notified_at=alert.last_notified_at if alert else None,
        snooze_until=alert.snooze_until if alert else None,
        firing_unannounced=alert.firing_unannounced if alert else False,
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

    Taken from the configuration when the outcome is recorded rather than shipped with it. A
    source's copy would cost Temporal payload on every batch, and no path writes a platform
    configuration between an evaluation and its record: a source keeps its own control plane and
    reaches these rows through a backfill a person runs.
    """
    return {
        "threshold_count": configuration.threshold_count,
        "threshold_operator": configuration.threshold_operator,
        "window_minutes": configuration.window_minutes,
        "evaluation_periods": configuration.evaluation_periods,
        "datapoints_to_alarm": configuration.datapoints_to_alarm,
        "cooldown_minutes": configuration.cooldown_minutes,
    }


def _event_row(
    configuration: PlatformAlertConfiguration,
    alert: PlatformAlert,
    outcome: PlatformAlertOutcome,
    previous_state: str,
    now: datetime,
) -> PlatformAlertEventRow:
    return PlatformAlertEventRow(
        team_id=configuration.team_id,
        configuration_id=configuration.id,
        alert_id=alert.id,
        grouping_key=alert.grouping_key,
        evaluation_key=outcome.evaluation_key,
        kind=outcome.kind.value,
        alert_name=configuration.name,
        previous_state=previous_state,
        state=outcome.new_state,
        value=outcome.value,
        labels=outcome.labels,
        condition_snapshot=_condition_snapshot(configuration),
        source_config_snapshot=configuration.source_config,
        query_duration_ms=outcome.query_duration_ms,
        error_message=outcome.error_message,
        consecutive_failures=outcome.consecutive_failures,
        muted_notification=outcome.muted_notification,
        occurred_at=now,
    )


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
        alerts = _alerts_for_write(team_id, configurations)

        rows: list[PlatformAlertEventRow] = []
        for configuration in configurations:
            outcome = by_id[str(configuration.id)]
            alert = alerts[str(configuration.id)]
            rows.append(_event_row(configuration, alert, outcome, alert.state, now))
            alert.state = outcome.new_state
            if outcome.notified:
                alert.last_notified_at = now
            alert.firing_unannounced = outcome.firing_unannounced

            configuration.consecutive_failures = outcome.consecutive_failures
            if outcome.disable:
                configuration.enabled = False
            configuration.next_check_at = advance_next_check_at(
                configuration.next_check_at,
                configuration.check_interval_minutes,
                now,
                shard_offset_seconds=compute_shard_offset_seconds(
                    configuration.id, configuration.check_interval_minutes
                ),
            )

        PlatformAlert.objects.for_team(team_id).bulk_update(
            list(alerts.values()), ["state", "last_notified_at", "firing_unannounced"]
        )
        PlatformAlertConfiguration.objects.for_team(team_id).bulk_update(
            configurations, ["consecutive_failures", "enabled", "next_check_at"]
        )

    recorded = insert_events(team_id, rows)
    if recorded < len(rows):
        safe_record(increment_history_rows_dropped, len(rows) - recorded)
    return len(configurations)


def upsert_configuration(upsert: PlatformAlertUpsert) -> bool:
    """Copies one source configuration in. Returns True when it created a row.

    Keyed on the row it came from, so a second run updates rather than duplicates.
    """
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
            },
        )
        alert = _alerts_for_write(upsert.team_id, [configuration])[str(configuration.id)]
        # State is left alone because a muted alert keeps tracking reality.
        alert.snooze_until = upsert.snooze_until
        alert.save(update_fields=["snooze_until"])
    return created
