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
# (realtime_cohort_calculation_workflow.py), keyset-paged on person_id: OFFSET paging
# would re-run the full aggregation per page, and each group's rows share one person_id
# so a cursor never splits a group across pages.
_OLD_MEMBERS_SQL_TEMPLATE = """
SELECT person_id
FROM cohort_membership
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s{cursor}
GROUP BY person_id
HAVING argMax(status, last_updated) = 'entered'
ORDER BY person_id
LIMIT %(limit)s
"""
_OLD_MEMBERS_FIRST_PAGE_SQL = _OLD_MEMBERS_SQL_TEMPLATE.format(cursor="")
_OLD_MEMBERS_NEXT_PAGE_SQL = _OLD_MEMBERS_SQL_TEMPLATE.format(cursor=" AND person_id > %(cursor)s")

_OLD_MEMBERS_SETTINGS = {
    # The old pipeline's own guards for this aggregation (EXTERNAL_GROUP_BY_MEMORY_RATIO):
    # without spill, a large cohort's GROUP BY person_id can OOM the offline pool.
    "max_bytes_ratio_before_external_group_by": 0.5,
    "distributed_aggregation_memory_efficient": 1,
    # person_id is a sort-key suffix under the two equality predicates, so aggregate in
    # order and stream: LIMIT stops the scan instead of materializing every group first.
    "optimize_aggregation_in_order": 1,
}

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
    """Converged entered-set of one cohort from ClickHouse cohort_membership (offline host).

    The full converged snapshot is read (not IN-filtered to the observed universe) because
    the classifier needs `old - O` to compute the missed-emission probe.
    """
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    members: set[str] = set()
    cursor: str | None = None
    while True:
        params: dict[str, object] = {"team_id": team_id, "cohort_id": cohort_id, "limit": page_size}
        if cursor is not None:
            params["cursor"] = cursor
        rows = sync_execute(
            _OLD_MEMBERS_FIRST_PAGE_SQL if cursor is None else _OLD_MEMBERS_NEXT_PAGE_SQL,
            params,
            settings=_OLD_MEMBERS_SETTINGS,
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
        # Lowercased to match the fold's person-id normalization (see fold.py).
        members.update(str(row[0]).lower() for row in rows)
        if len(rows) < page_size:
            return members
        cursor = str(rows[-1][0])


def make_activity_probe(team_id: int) -> Callable[[Sequence[str], datetime], set[str]]:
    """Missed-emission probe: which of `person_ids` had any event at/after `cutoff`."""

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
            # Lowercased to match the fold's person-id normalization (see fold.py).
            active.update(str(row[0]).lower() for row in rows)
        return active

    return probe
