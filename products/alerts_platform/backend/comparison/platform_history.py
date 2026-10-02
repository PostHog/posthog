"""The platform half of a comparison: the checks the platform recorded in a window.

The history row carries `configuration_id`, and a correspondence needs `legacy_configuration_id`,
which lives on `PlatformAlertConfiguration` in Postgres. So a read is a Postgres query followed by
a ClickHouse one, and that stays true whatever columns the row grows.

Restricting the ClickHouse read to one source's configurations is what selects a source. The row's
own `source_kind` column would select the same rows, but the Postgres query has to run first anyway
for the legacy ids, so the configuration list costs nothing extra.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields
from datetime import datetime
from uuid import UUID

from posthog.clickhouse.client import query_with_columns
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.alerts_platform.backend.facade.contracts import PlatformCheck, SourceKind
from products.alerts_platform.backend.models import PlatformAlertConfiguration
from products.alerts_platform.backend.models.platform_alert_events_sql import PLATFORM_ALERT_EVENTS_TABLE

# Refused rather than cut short, because an agreement rate over a silently truncated window
# is worse than no rate at all.
MAX_CHECKS_PER_WINDOW = 200_000

# Derived from the contract, so a field added there cannot be left out of the SELECT.
_COLUMNS = tuple(f.name for f in fields(PlatformCheck) if f.name not in ("team_id", "legacy_configuration_id"))

# `LIMIT 1 BY` deduplicates on the pair the writer names, because the insert token only covers a
# retry of the same batch and the engine remembers a bounded window of tokens. The ORDER BY is the
# table's sort key with `team_id` fixed, so rows stream in order and arrive grouped by alert.
_SELECT_SQL = f"""
SELECT {", ".join(_COLUMNS)}
FROM {PLATFORM_ALERT_EVENTS_TABLE}
WHERE team_id = %(team_id)s
  AND configuration_id IN %(configuration_ids)s
  AND occurred_at >= %(since)s
  AND occurred_at < %(until)s
ORDER BY configuration_id, alert_id, occurred_at, evaluation_key
LIMIT 1 BY alert_id, evaluation_key
LIMIT %(limit)s
"""


class ComparisonWindowTooLarge(Exception):
    """The window holds more checks than one read will return."""


class UnregisteredSource(Exception):
    """The configuration model has no `source_kind` for this source."""


def read_platform_checks(
    *,
    team_id: int,
    source: SourceKind,
    since: datetime,
    until: datetime,
) -> Sequence[PlatformCheck]:
    """Every check the platform recorded for one source and team in `[since, until)`.

    A window wider than the shorter of the two retentions is not available: the platform's rows
    expire on a 90-day ClickHouse TTL, and each source ages its own history on its own schedule.
    """
    if source.value not in PlatformAlertConfiguration.SourceKind.values:
        # Two SourceKind enums exist and have already drifted. Without this an unregistered source
        # reads as a source that made no checks, which is the answer a comparison must never give.
        raise UnregisteredSource(f"{source.value} is not a source_kind the configuration model accepts")

    legacy_ids: dict[UUID, UUID | None] = dict(
        PlatformAlertConfiguration.objects.for_team(team_id)
        .filter(source_kind=source.value)
        .values_list("id", "legacy_configuration_id")
    )
    if not legacy_ids:
        return ()

    tag_queries(product=Product.PLATFORM_AND_SUPPORT, feature=Feature.ALERTING)
    rows = query_with_columns(
        _SELECT_SQL,
        {
            "team_id": team_id,
            "configuration_ids": list(legacy_ids),
            "since": since,
            "until": until,
            "limit": MAX_CHECKS_PER_WINDOW + 1,
        },
        team_id=team_id,
    )
    if len(rows) > MAX_CHECKS_PER_WINDOW:
        raise ComparisonWindowTooLarge(
            f"{since.isoformat()} to {until.isoformat()} holds over {MAX_CHECKS_PER_WINDOW} checks; narrow it"
        )

    return tuple(
        PlatformCheck(team_id=team_id, legacy_configuration_id=legacy_ids[row["configuration_id"]], **row)
        for row in rows
    )
