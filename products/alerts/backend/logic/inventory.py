"""How many platform alerts exist, what state they are in, and how their checks spread, across every team.

Counted once a minute by its own schedule for the worker health dashboard, apart from the tick. Every label combination
is returned, zeros included, because a gauge keeps its last value until it is set again.
"""

import datetime as dt

from django.db.models import BigIntegerField, Count, F, IntegerField, Q
from django.db.models.functions import Cast, Extract, Mod

from posthog.dataclasses import frozen
from posthog.models.utils import execute_with_timeout

from products.alerts.backend.facade.contracts import SourceKind
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration

# Per statement. The counts scan every row, unlike discovery, which reads only the due index,
# so a slow scan fails fast and holds no Postgres connection the tick needs.
INVENTORY_STATEMENT_TIMEOUT_MS = 1000


@frozen
class ConfigurationCount:
    source: str
    enabled: bool
    count: int


@frozen
class AlertCount:
    source: str
    state: str
    muted: bool
    count: int


@frozen
class SlotCount:
    source: str
    interval_minutes: int
    slot: int
    count: int


@frozen
class LargestTeam:
    source: str
    count: int


@frozen
class AlertInventory:
    configurations: tuple[ConfigurationCount, ...]
    # Runtime rows of enabled configurations only. A disabled configuration is counted above.
    alerts: tuple[AlertCount, ...]
    slots: tuple[SlotCount, ...]
    largest_teams: tuple[LargestTeam, ...]


def count_inventory(now: dt.datetime) -> AlertInventory:
    # Cross-team by definition, like demand discovery. Every query is evaluated inside the block,
    # because the timeout is transaction-local.
    with execute_with_timeout(INVENTORY_STATEMENT_TIMEOUT_MS):
        configuration_counts = {
            (row["source_kind"], row["enabled"]): row["n"]
            for row in PlatformAlertConfiguration.objects.unscoped()
            .values("source_kind", "enabled")
            .annotate(n=Count("id"))
        }
        alert_counts = {
            (row["configuration__source_kind"], row["state"]): (row["total"], row["muted"])
            for row in PlatformAlert.objects.unscoped()
            .filter(configuration__enabled=True)
            .values("configuration__source_kind", "state")
            .annotate(total=Count("id"), muted=Count("id", filter=Q(snooze_until__gt=now)))
        }
        # The minute within its cadence that a configuration is due in. A configuration never
        # checked has no due time yet, so it is left out.
        slot_counts = {
            (row["source_kind"], row["check_interval_minutes"], row["slot"]): row["n"]
            for row in PlatformAlertConfiguration.objects.unscoped()
            .filter(enabled=True, next_check_at__isnull=False)
            .annotate(
                slot=Mod(
                    Cast(Extract("next_check_at", "epoch"), BigIntegerField()) / 60,
                    F("check_interval_minutes"),
                    output_field=IntegerField(),
                )
            )
            .values("source_kind", "check_interval_minutes", "slot")
            .annotate(n=Count("id"))
        }
        largest_team_counts = {
            source.value: PlatformAlertConfiguration.objects.unscoped()
            .filter(enabled=True, source_kind=source.value)
            .values("team_id")
            .annotate(n=Count("id"))
            .order_by("-n")
            .values_list("n", flat=True)
            .first()
            or 0
            for source in SourceKind
        }

    configurations: list[ConfigurationCount] = []
    alerts: list[AlertCount] = []
    slots: list[SlotCount] = []
    for source in SourceKind:
        for enabled in (True, False):
            configurations.append(
                ConfigurationCount(
                    source=source.value, enabled=enabled, count=configuration_counts.get((source.value, enabled), 0)
                )
            )
        for state in PlatformAlert.State:
            total, muted = alert_counts.get((source.value, state.value), (0, 0))
            alerts.append(AlertCount(source=source.value, state=state.value, muted=True, count=muted))
            alerts.append(AlertCount(source=source.value, state=state.value, muted=False, count=total - muted))
        intervals = sorted({interval for (kind, interval, _) in slot_counts if kind == source.value})
        for interval in intervals:
            for slot in range(interval):
                slots.append(
                    SlotCount(
                        source=source.value,
                        interval_minutes=interval,
                        slot=slot,
                        count=slot_counts.get((source.value, interval, slot), 0),
                    )
                )
    return AlertInventory(
        configurations=tuple(configurations),
        alerts=tuple(alerts),
        slots=tuple(slots),
        largest_teams=tuple(LargestTeam(source=source, count=count) for source, count in largest_team_counts.items()),
    )
