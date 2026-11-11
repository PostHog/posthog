"""How many platform alerts exist and what state they are in, across every team.

Counted once a tick for the worker health dashboard. Every source and label
combination is returned, zeros included, because a gauge keeps its last value until it is set again.
"""

import datetime as dt

from django.db.models import Count, Q

from posthog.dataclasses import frozen
from posthog.models.utils import execute_with_timeout

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

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
class SourceInventory:
    source: SourceKind
    configurations: tuple[ConfigurationCount, ...]
    alerts: tuple[AlertCount, ...]


def count_inventory(now: dt.datetime) -> tuple[SourceInventory, ...]:
    # Cross-team by definition, like demand discovery. Both queries are evaluated inside the block,
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
            )
        )
    return tuple(inventories)
