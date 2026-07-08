"""Old-pipeline snapshot and warmup-probe reads (ClickHouse) + cohort universe (ORM)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from django.db.models import QuerySet

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.schema_enums import ProductKey

from products.cohorts.backend.models.cohort import Cohort, CohortType

# Same argMax convergence the old pipeline itself uses to read cohort_membership
# (realtime_cohort_calculation_workflow.py); paged to bound memory.
_OLD_MEMBERS_SQL = """
SELECT person_id
FROM cohort_membership
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s
GROUP BY person_id
HAVING argMax(status, last_updated) = 'entered'
ORDER BY person_id
LIMIT %(limit)s OFFSET %(offset)s
"""

_ACTIVE_PERSONS_SQL = """
SELECT DISTINCT person_id
FROM events
WHERE team_id = %(team_id)s AND timestamp >= %(cutoff)s AND person_id IN %(person_ids)s
"""

_ACTIVITY_CHUNK = 1000


def load_realtime_cohorts(team_id: int) -> QuerySet[Cohort]:
    """The rows the Rust filter loader reads (loader.rs REALTIME_COHORTS_SQL).

    Narrowed to the fields the parity report consumes.
    """
    return (
        Cohort.objects.filter(
            team_id=team_id,
            cohort_type=CohortType.REALTIME,
            deleted=False,
            filters__isnull=False,
        )
        .only("id", "name", "filters", "last_realtime_cohort_calculation_at")
        .order_by("id")
    )


def load_old_membership(team_id: int, cohort_id: int, *, page_size: int = 500_000) -> set[str]:
    """Converged entered-set of one cohort from ClickHouse cohort_membership (offline host)."""
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    members: set[str] = set()
    offset = 0
    while True:
        rows = sync_execute(
            _OLD_MEMBERS_SQL,
            {"team_id": team_id, "cohort_id": cohort_id, "limit": page_size, "offset": offset},
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
        members.update(str(row[0]).lower() for row in rows)
        if len(rows) < page_size:
            return members
        offset += page_size


def make_activity_probe(team_id: int) -> Callable[[Sequence[str], datetime], set[str]]:
    """R-WARMUP probe: which of `person_ids` had any event at/after `cutoff`."""

    def probe(person_ids: Sequence[str], cutoff: datetime) -> set[str]:
        tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
        active: set[str] = set()
        for start in range(0, len(person_ids), _ACTIVITY_CHUNK):
            chunk = list(person_ids[start : start + _ACTIVITY_CHUNK])
            rows = sync_execute(
                _ACTIVE_PERSONS_SQL,
                {"team_id": team_id, "cutoff": cutoff, "person_ids": chunk},
                workload=Workload.OFFLINE,
                team_id=team_id,
            )
            active.update(str(row[0]).lower() for row in rows)
        return active

    return probe
