"""Reads and writes for the skeleton shared alert tables.

A source decides whether its data breached; everything about what that means for the alert,
and every write to these rows, stays here. A source never holds one of these models.
"""

from collections.abc import Sequence
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from products.alerts.backend.facade.contracts import PlatformAlertCheck, PlatformAlertOutcome, PlatformAlertUpsert
from products.alerts.backend.facade.scheduling import (
    advance_next_check_at,
    compute_shard_offset_seconds,
    parse_blocked_windows_tuples,
    scan_next_unblocked_utc,
)
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


def due_checks(team_id: int, source_kind: str, slot: str, cutoff: datetime) -> tuple[PlatformAlertCheck, ...]:
    """Every configuration in one batch key, with its runtime state, ready to evaluate."""
    configurations = list(
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(enabled=True, source_kind=source_kind)
        .filter(due_q(cutoff))
        # Ordered so a retried attempt keeps the same alerts under any downstream cap.
        .order_by("id")
    )
    configurations = [c for c in configurations if slot_of(c.next_check_at, cutoff) == slot]
    if not configurations:
        return ()

    alerts = _existing_alerts(team_id, configurations)
    return tuple(_check(c, alerts.get(str(c.id))) for c in configurations)


def _check(c: PlatformAlertConfiguration, alert: PlatformAlert | None) -> PlatformAlertCheck:
    return PlatformAlertCheck(
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
    )


def slot_of(next_check_at: datetime | None, cutoff: datetime) -> str:
    """The minute a configuration is due for. One that has never been checked has no due time
    of its own, so it belongs to the tick that found it.

    The single definition: discovery mints a key with it and this filters rows back down to
    one. If the two ever disagreed, every alert would evaluate nothing, silently.
    """
    return (next_check_at or cutoff).replace(second=0, microsecond=0).isoformat()


def record_outcomes(
    team_id: int, outcomes: Sequence[PlatformAlertOutcome], now: datetime, *, team_timezone: str
) -> int:
    """Persists a batch's decisions and advances each configuration's schedule.

    Two statements rather than two per alert, in one transaction, so a crash between them cannot
    leave an alert marked as notified while its schedule still says the check is due. The schedule
    advances the way the source's own stack advances it: sharded across the cadence so a fleet does
    not converge on one minute, then pushed past any blocked window.

    Safe to run twice on the same batch. An attempt that commits leaves every configuration due
    after `now`, and a replay of that attempt skips those rows rather than advancing them a second
    time and skipping a cycle.
    Returns how many configurations it wrote, which is fewer than it was given when a replay
    finds rows an earlier attempt already advanced.
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

        for configuration in configurations:
            outcome = by_id[str(configuration.id)]
            alert = alerts[str(configuration.id)]
            alert.state = outcome.new_state
            if outcome.notified:
                alert.last_notified_at = now

            configuration.consecutive_failures = outcome.consecutive_failures
            if outcome.disable:
                configuration.enabled = False
            next_check_at = advance_next_check_at(
                configuration.next_check_at,
                configuration.check_interval_minutes,
                now,
                shard_offset_seconds=compute_shard_offset_seconds(
                    configuration.id, configuration.check_interval_minutes
                ),
            )
            windows = parse_blocked_windows_tuples(configuration.schedule_restriction)
            configuration.next_check_at = (
                scan_next_unblocked_utc(next_check_at, team_timezone, windows) or next_check_at
            )

        PlatformAlert.objects.for_team(team_id).bulk_update(list(alerts.values()), ["state", "last_notified_at"])
        PlatformAlertConfiguration.objects.for_team(team_id).bulk_update(
            configurations, ["consecutive_failures", "enabled", "next_check_at"]
        )
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
        # Logs-style evaluation honors `snooze_until` only while the state is SNOOZED.
        if upsert.snooze_until is not None and upsert.snooze_until > timezone.now():
            alert.state = PlatformAlert.State.SNOOZED
        elif alert.state == PlatformAlert.State.SNOOZED:
            alert.state = PlatformAlert.State.NOT_FIRING
        alert.snooze_until = upsert.snooze_until
        alert.save(update_fields=["state", "snooze_until"])
    return created
