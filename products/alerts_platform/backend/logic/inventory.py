"""How many platform alerts exist and what state they are in, across every team.

Counted once a tick for the worker health dashboard, one source at a time. Every label combination
is returned, zeros included, because a gauge keeps its last value until it is set again.
"""

import datetime as dt

from django.db.models import Count, Q

from posthog.dataclasses import frozen
from posthog.models.utils import execute_with_timeout

from products.alerts_platform.backend.facade.contracts import SourceKind
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.alerts_platform.backend.models import PlatformAlert, PlatformAlertConfiguration

# Per statement. The counts scan every row of a source, unlike discovery, which reads only the due
# index, so a slow scan fails fast and holds no Postgres connection the tick needs.
INVENTORY_STATEMENT_TIMEOUT_MS = 1000


@frozen
class ConfigurationCount:
    enabled: bool
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


def count_source_inventory(source: SourceKind, now: dt.datetime) -> SourceInventory:
    # Cross-team by definition, like demand discovery. Both queries are evaluated inside the block,
    # because the timeout is transaction-local.
    with execute_with_timeout(INVENTORY_STATEMENT_TIMEOUT_MS):
        configuration_counts = {
            row["enabled"]: row["n"]
            for row in PlatformAlertConfiguration.objects.unscoped()
            .filter(source_kind=source.value)
            .values("enabled")
            .annotate(n=Count("id"))
        }
        muted = Q(snooze_until__gt=now) | Q(configuration__snooze_until__gt=now)
        alert_counts = {
            row["state"]: (row["total"], row["muted"])
            for row in PlatformAlert.objects.unscoped()
            .filter(configuration__source_kind=source.value, configuration__enabled=True)
            .values("state")
            .annotate(total=Count("id"), muted=Count("id", filter=muted))
        }

    alerts: list[AlertCount] = []
    for state in PlatformAlertState:
        total, muted_count = alert_counts.get(state.value, (0, 0))
        alerts.append(AlertCount(state=state, muted=True, count=muted_count))
        alerts.append(AlertCount(state=state, muted=False, count=total - muted_count))
    return SourceInventory(
        source=source,
        configurations=tuple(
            ConfigurationCount(enabled=enabled, count=configuration_counts.get(enabled, 0)) for enabled in (True, False)
        ),
        alerts=tuple(alerts),
    )
