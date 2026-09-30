"""How many platform alerts exist, and what state they are in, across every team.

Counted once per orchestration tick for the worker health dashboard. Every label combination
is returned, zeros included, because a gauge keeps its last value until it is set again.
"""

import datetime as dt

from django.db.models import Count, Q

from posthog.dataclasses import frozen
from posthog.models.utils import execute_with_timeout

from products.alerts.backend.facade.contracts import SourceKind
from products.alerts.backend.models import PlatformAlert, PlatformAlertConfiguration

# Per statement. Both counts scan every row, unlike discovery, which reads only the due index.
# The count runs inside the discovery activity, so a slow scan must fail fast and leave that
# activity's time budget to discovery.
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
class AlertInventory:
    configurations: tuple[ConfigurationCount, ...]
    # Runtime rows of enabled configurations only. A disabled configuration is counted above.
    alerts: tuple[AlertCount, ...]


def count_inventory(now: dt.datetime) -> AlertInventory:
    # Cross-team by definition, like demand discovery. Both queries are evaluated inside the block,
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

    configurations: list[ConfigurationCount] = []
    alerts: list[AlertCount] = []
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
    return AlertInventory(configurations=tuple(configurations), alerts=tuple(alerts))
