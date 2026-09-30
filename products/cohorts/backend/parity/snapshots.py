"""Legacy cohortpeople population read (ClickHouse) + cohort universe (ORM)."""

from __future__ import annotations

from django.db.models import QuerySet

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.schema_enums import ProductKey

from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.parity.oracle import OracleSetTooLarge

# The keyset cursor casts explicitly: person_id is a UUID column, and the cursor must compare in the
# column's own (UUID) order, the same order the ORDER BY paginates in. A bare string bind leans on
# ClickHouse coercing the constant, so the cast keeps the contract visible.
_CURSOR_PREDICATE = " AND person_id > toUUID(%(cursor)s)"

# The legacy batch calculation's population, at the version the cohort page pins
# (in_cohort.py lowers a cohort property to `raw_cohort_people ... AND version = N`).
# `sum(sign) > 0` is the CollapsingMergeTree contract of the table; the calc path never
# tombstones the pinned version, so today it agrees with the UI's DISTINCT form.
_POPULATION_SQL_TEMPLATE = """
SELECT person_id
FROM cohortpeople
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND version = %(version)s{cursor}
GROUP BY person_id
HAVING sum(sign) > 0
ORDER BY person_id
LIMIT %(limit)s
"""
_POPULATION_FIRST_PAGE_SQL = _POPULATION_SQL_TEMPLATE.format(cursor="")
_POPULATION_NEXT_PAGE_SQL = _POPULATION_SQL_TEMPLATE.format(cursor=_CURSOR_PREDICATE)

# Distinct from oracle.py's _MEMBER_SET_SETTINGS, which bounds single-shot leaf recomputes with
# query timeouts; these paged reads stream instead, so the ClickHouse side stays bounded and only
# the Python-side set can grow without limit (see _paged_person_ids for where that is capped).
_PAGED_MEMBER_SETTINGS = {
    # Without spill, a large cohort's GROUP BY person_id can OOM the offline pool.
    "max_bytes_ratio_before_external_group_by": 0.5,
    "distributed_aggregation_memory_efficient": 1,
    # cohortpeople leads its sort key with (team_id, cohort_id), leaving person_id the first sort
    # column the equality filters do not pin, so aggregate in order and stream: LIMIT stops the
    # scan instead of materializing every group first.
    "optimize_aggregation_in_order": 1,
}


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
        .only(
            "id",
            "name",
            "filters",
            "version",
            "last_calculation",
            "is_calculating",
        )
        .order_by("id")
    )


def _paged_person_ids(
    *,
    first_page_sql: str,
    next_page_sql: str,
    params: dict[str, object],
    team_id: int,
    page_size: int,
    limit: int,
    label: str,
) -> set[str]:
    """Keyset-paged person-id read: OFFSET would re-run the aggregation per page, and a group's
    rows all share one person_id so a cursor never splits one.

    ``limit`` caps the Python-side set (the query itself spills and streams): a single cohort can
    hold up to the 20M realtime ceiling, which no toolbox pod survives as a set of id strings, so
    past the cap the read raises :class:`OracleSetTooLarge` instead of OOMing a multi-cohort run.
    The check runs inside the page loop so at most ``limit + page_size`` ids are ever resident.
    """
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    ids: set[str] = set()
    cursor: str | None = None
    while True:
        page_params: dict[str, object] = {**params, "limit": page_size}
        if cursor is not None:
            page_params["cursor"] = cursor
        rows = sync_execute(
            first_page_sql if cursor is None else next_page_sql,
            page_params,
            settings=_PAGED_MEMBER_SETTINGS,
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
        # Lowercased to match the fold's person-id normalization (see fold.py).
        ids.update(str(row[0]).lower() for row in rows)
        if len(ids) > limit:
            raise OracleSetTooLarge(label, limit)
        if len(rows) < page_size:
            return ids
        cursor = str(rows[-1][0])


def load_cohort_population(
    team_id: int, cohort_id: int, version: int, *, limit: int, page_size: int = 500_000
) -> set[str]:
    """The legacy batch calculation's population of one cohort, at its pinned version.

    Raises :class:`OracleSetTooLarge` past ``limit`` so an oversized cohort becomes a skip row
    rather than the end of the whole run.
    """
    return _paged_person_ids(
        first_page_sql=_POPULATION_FIRST_PAGE_SQL,
        next_page_sql=_POPULATION_NEXT_PAGE_SQL,
        params={"team_id": team_id, "cohort_id": cohort_id, "version": version},
        team_id=team_id,
        page_size=page_size,
        limit=limit,
        label=f"cohort {cohort_id} population at version {version}",
    )
