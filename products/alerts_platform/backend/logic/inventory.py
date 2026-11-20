"""How many platform alerts exist and what state they are in, across every team.

Counted once a tick for the worker health dashboard. Every source and label
combination is returned, zeros included, because a gauge keeps its last value until it is set again.
"""

import datetime as dt
from collections.abc import Mapping
from typing import Any

from django.db.models import Case, Count, DateTimeField, DurationField, ExpressionWrapper, F, Min, Q, Value, When
from django.db.models.functions import Greatest

from posthog.dataclasses import frozen
from posthog.models.utils import execute_with_timeout

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.alerts_platform.backend.logic.platform_lifecycle import suppressed
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

# Twice the cadence, so one tick a busy pool skipped is not a miss. A calendar recurrence has no
# cadence in minutes, so it gets a fixed allowance.
OVERDUE_GRACE_MIN = dt.timedelta(minutes=2)
OVERDUE_GRACE_PER_INTERVAL_MINUTE = dt.timedelta(minutes=2)
OVERDUE_GRACE_CALENDAR = dt.timedelta(hours=2)

# Per statement. The counts scan every configuration, unlike discovery, which reads only the due index,
# so a slow scan fails fast and holds no Postgres connection the tick needs.
INVENTORY_STATEMENT_TIMEOUT_MS = 500


@frozen
class ConfigurationCount:
    enabled: bool
    # Which stack decides and sends for the alert, so the count shows how far a cutover has gone.
    owner: PlatformAlertOwner
    count: int


@frozen
class AlertCount:
    state: PlatformAlertState
    muted: bool
    count: int


@frozen
class OverdueCount:
    """Enabled configurations whose check has not run when it should have, whatever held it back.

    State-based on purpose: each early return in a source would need its own counter, and a cause
    nobody has named yet moves none of them. A check that is late shows up here regardless.
    """

    owner: PlatformAlertOwner
    overdue: int
    unscheduled: int
    oldest_due_seconds: float
    # BROKEN is held back on purpose, so it is counted apart from overdue.
    broken: int


@frozen
class SourceInventory:
    source: SourceKind
    configurations: tuple[ConfigurationCount, ...]
    alerts: tuple[AlertCount, ...]
    overdue: tuple[OverdueCount, ...] = ()


def _overdue_grace() -> Case:
    return Case(
        When(recurrence_unit__isnull=False, then=Value(OVERDUE_GRACE_CALENDAR)),
        default=Greatest(
            Value(OVERDUE_GRACE_MIN),
            F("check_interval_minutes") * Value(OVERDUE_GRACE_PER_INTERVAL_MINUTE),
            output_field=DurationField(),
        ),
        output_field=DurationField(),
    )


def count_inventory(now: dt.datetime) -> tuple[SourceInventory, ...]:
    # Cross-team by definition, like demand discovery. Every query is evaluated inside the block,
    # because the timeout is transaction-local.
    with execute_with_timeout(INVENTORY_STATEMENT_TIMEOUT_MS):
        configuration_counts = {
            (row["source_kind"], row["enabled"], row["owner"]): row["n"]
            for row in PlatformAlertConfiguration.objects.unscoped()
            .values("source_kind", "enabled", "owner")
            .annotate(n=Count("id"))
        }
        is_muted = Q(snooze_until__gt=now) | Q(configuration__snooze_until__gt=now)
        alert_counts = {
            (row["configuration__source_kind"], row["state"]): (row["total"], row["muted"])
            for row in PlatformAlert.objects.unscoped()
            .filter(configuration__enabled=True)
            .values("configuration__source_kind", "state")
            .annotate(total=Count("id"), muted=Count("id", filter=is_muted))
        }
        checked = ~suppressed()
        overdue_before = ExpressionWrapper(Value(now) - _overdue_grace(), output_field=DateTimeField())
        overdue_counts = {
            (row["source_kind"], row["owner"]): row
            for row in PlatformAlertConfiguration.objects.unscoped()
            .filter(enabled=True)
            .values("source_kind", "owner")
            .annotate(
                overdue=Count("id", filter=checked & Q(next_check_at__lt=overdue_before)),
                unscheduled=Count("id", filter=checked & Q(next_check_at__isnull=True)),
                oldest_due_at=Min("next_check_at", filter=checked & Q(next_check_at__lte=now)),
                broken=Count("id", filter=suppressed()),
            )
        }

    inventories: list[SourceInventory] = []
    for source in SourceKind:
        alerts: list[AlertCount] = []
        for state in PlatformAlertState:
            total, muted_count = alert_counts.get((source.value, state.value), (0, 0))
            alerts.append(AlertCount(state=state, muted=True, count=muted_count))
            alerts.append(AlertCount(state=state, muted=False, count=total - muted_count))
        inventories.append(
            SourceInventory(
                source=source,
                configurations=tuple(
                    ConfigurationCount(
                        enabled=enabled,
                        owner=owner,
                        count=configuration_counts.get((source.value, enabled, owner.value), 0),
                    )
                    for enabled in (True, False)
                    for owner in PlatformAlertOwner
                ),
                alerts=tuple(alerts),
                overdue=tuple(
                    _overdue_count(owner, overdue_counts.get((source.value, owner.value)), now)
                    for owner in PlatformAlertOwner
                ),
            )
        )
    return tuple(inventories)


def _overdue_count(owner: PlatformAlertOwner, row: Mapping[str, Any] | None, now: dt.datetime) -> OverdueCount:
    if row is None:
        return OverdueCount(owner=owner, overdue=0, unscheduled=0, oldest_due_seconds=0, broken=0)
    oldest_due_at = row["oldest_due_at"]
    return OverdueCount(
        owner=owner,
        overdue=row["overdue"],
        unscheduled=row["unscheduled"],
        oldest_due_seconds=(now - oldest_due_at).total_seconds() if oldest_due_at is not None else 0,
        broken=row["broken"],
    )
