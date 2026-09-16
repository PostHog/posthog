"""Reads and writes for the skeleton shared alert tables.

A source decides whether its data breached; everything about what that means for the alert,
and every write to these rows, stays here. A source never holds one of these models.
"""

from collections.abc import Sequence
from datetime import datetime

from django.db.models import Q

from products.alerts.backend.facade.contracts import WIPAlertCheck, WIPAlertOutcome, WIPAlertUpsert
from products.alerts.backend.facade.scheduling import (
    advance_next_check_at,
    compute_shard_offset_seconds,
    parse_blocked_windows_tuples,
    scan_next_unblocked_utc,
)
from products.alerts.backend.models import WIPAlert, WIPAlertConfiguration


def _runtime_alerts(team_id: int, configurations: Sequence[WIPAlertConfiguration]) -> dict[str, WIPAlert]:
    """One runtime row per configuration, creating any that has none yet.

    The grouping key is empty until a source groups its results, so today this is the whole of
    an alert's state and a real key needs no new table.
    """
    existing = {
        str(alert.configuration_id): alert
        for alert in WIPAlert.objects.for_team(team_id).filter(configuration__in=configurations, grouping_key="")
    }
    missing = [c for c in configurations if str(c.id) not in existing]
    if missing:
        # ignore_conflicts leans on the unique constraint, so a concurrent cycle creating the
        # same row is not an error.
        WIPAlert.objects.bulk_create(
            [WIPAlert(team_id=team_id, configuration=c, grouping_key="") for c in missing],
            ignore_conflicts=True,
        )
        existing.update(
            {
                str(alert.configuration_id): alert
                for alert in WIPAlert.objects.for_team(team_id).filter(configuration__in=missing, grouping_key="")
            }
        )
    return existing


def due_checks(team_id: int, source_kind: str, slot: str, cutoff: datetime) -> tuple[WIPAlertCheck, ...]:
    """Every configuration in one batch key, with its runtime state, ready to evaluate."""
    configurations = list(
        WIPAlertConfiguration.objects.for_team(team_id)
        .filter(enabled=True, source_kind=source_kind)
        .filter(Q(next_check_at__lte=cutoff) | Q(next_check_at__isnull=True))
        # Ordered so a retried attempt keeps the same alerts under any downstream cap.
        .order_by("id")
    )
    configurations = [c for c in configurations if slot_of(c.next_check_at, cutoff) == slot]
    if not configurations:
        return ()

    alerts = _runtime_alerts(team_id, configurations)
    return tuple(
        WIPAlertCheck(
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
            state=alerts[str(c.id)].state,
            last_notified_at=alerts[str(c.id)].last_notified_at,
            snooze_until=alerts[str(c.id)].snooze_until,
        )
        for c in configurations
    )


def slot_of(next_check_at: datetime | None, cutoff: datetime) -> str:
    """The minute a configuration is due for. One that has never been checked has no due time
    of its own, so it belongs to the tick that found it.

    The single definition: discovery mints a key with it and this filters rows back down to
    one. If the two ever disagreed, every alert would evaluate nothing, silently.
    """
    return (next_check_at or cutoff).replace(second=0, microsecond=0).isoformat()


def record_outcomes(team_id: int, outcomes: Sequence[WIPAlertOutcome], now: datetime, *, team_timezone: str) -> None:
    """Persists a batch's decisions and advances each configuration's schedule.

    Two statements rather than two per alert. The schedule advances the way the source's own
    stack advances it: sharded across the cadence so a fleet does not converge on one minute,
    then pushed past any blocked window.
    """
    if not outcomes:
        return
    by_id = {str(o.configuration_id): o for o in outcomes}
    configurations = list(WIPAlertConfiguration.objects.for_team(team_id).filter(id__in=by_id))
    alerts = _runtime_alerts(team_id, configurations)

    for configuration in configurations:
        outcome = by_id[str(configuration.id)]
        alert = alerts[str(configuration.id)]
        alert.state = outcome.new_state
        if outcome.notified:
            alert.last_notified_at = now

        configuration.consecutive_failures = outcome.consecutive_failures
        next_check_at = advance_next_check_at(
            configuration.next_check_at,
            configuration.check_interval_minutes,
            now,
            shard_offset_seconds=compute_shard_offset_seconds(configuration.id, configuration.check_interval_minutes),
        )
        windows = parse_blocked_windows_tuples(configuration.schedule_restriction)
        configuration.next_check_at = scan_next_unblocked_utc(next_check_at, team_timezone, windows) or next_check_at

    WIPAlert.objects.bulk_update(list(alerts.values()), ["state", "last_notified_at"])
    WIPAlertConfiguration.objects.bulk_update(configurations, ["consecutive_failures", "next_check_at"])


def upsert_configuration(upsert: WIPAlertUpsert) -> bool:
    """Copies one source configuration in. Returns True when it created a row.

    Keyed on the row it came from, so a second run updates rather than duplicates.
    """
    _, created = WIPAlertConfiguration.objects.unscoped().update_or_create(
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
    return created
