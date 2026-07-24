"""Recompute-oracle reads: ClickHouse member-set / segmentation queries + the Django run context.

Mixed IO (ClickHouse + ORM), precedented by :mod:`.snapshots`. The pure classification of what these
return lives in :mod:`.recompute`; this module only fetches.

Person resolution mirrors the seeder's overrides join (``rust/cohort-seeder/src/clickhouse/sql.rs``):
``if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)`` with ``argMax(person_id, version) …
HAVING argMax(is_deleted, version) = 0`` from ``person_distinct_id_overrides``. All tz-date arithmetic
is Python-side (:mod:`.tzdates`); SQL only ever compares ``e.timestamp`` against UTC datetime params or
converts the ``e.timestamp`` *column* via ``toDate(<column>, %(seg_tz)s)`` — never ``toDate(<param>, tz)``.
Person ids are lowercased at the boundary to match the fold's normalization (see ``fold.py``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.schema_enums import ProductKey

from products.cohorts.backend.models.backfill import (
    CohortBackfillChunk,
    CohortBackfillChunkStatus,
    CohortBackfillRun,
    CohortBackfillRunCohort,
)
from products.cohorts.backend.models.cohort import Cohort
from products.cohorts.backend.parity.recompute import DayMatch, OracleLeaf, RunContext
from products.cohorts.backend.parity.tzdates import day_of_instant, resolve_zoneinfo, window_start_utc

# Never interpolated from user text — the op is one of these fixed comparators, chosen by key.
_OP_SQL = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "eq": "="}

# The seeder's overrides join, shared by both reads.
_OVERRIDES_JOIN = """
    LEFT JOIN (
        SELECT distinct_id, argMax(person_id, version) AS person_id
        FROM person_distinct_id_overrides
        WHERE team_id = %(team_id)s
        GROUP BY distinct_id
        HAVING argMax(is_deleted, version) = 0
    ) AS ov ON e.distinct_id = ov.distinct_id
"""

_MEMBER_SET_SQL = """
SELECT person_id, count() AS match_count
FROM (
    SELECT toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id
    FROM events AS e{overrides_join}
    WHERE e.team_id = %(team_id)s
      AND e.event = %(event_name)s
      AND e.timestamp >= %(window_start)s
      AND e.timestamp <= %(at)s
)
GROUP BY person_id
HAVING match_count >= 1 AND match_count {op} %(op_value)s
"""

_SEGMENTATION_SQL = """
SELECT toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) AS person_id,
       toDate(e.timestamp, %(seg_tz)s) AS day,
       multiIf(e.timestamp >= %(grace_start)s, 'grace',
               e.timestamp >= %(boundary_at)s, 'post_boundary',
               'pre_boundary') AS bucket,
       count() AS matches
FROM events AS e{overrides_join}
WHERE e.team_id = %(team_id)s
  AND e.event = %(event_name)s
  AND e.timestamp >= %(scan_start)s
  AND e.timestamp <= %(at)s
  AND toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)) IN %(person_ids)s
GROUP BY person_id, day, bucket
"""

# The GROUP BY person_id can be large for a broad event; spill like the old-membership read.
_MEMBER_SET_SETTINGS = {
    "max_bytes_ratio_before_external_group_by": 0.5,
    "distributed_aggregation_memory_efficient": 1,
}

_SEGMENTATION_CHUNK = 1000


def load_leaf_members(team_id: int, leaf: OracleLeaf, *, at: datetime, tz: ZoneInfo) -> set[str]:
    """Persons matching one leaf's ``count >= 1 AND op(count)`` predicate over its whole-day window."""
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    window_start = window_start_utc(at, leaf.window_days, tz)
    sql = _MEMBER_SET_SQL.format(overrides_join=_OVERRIDES_JOIN, op=_OP_SQL[leaf.op])
    rows = sync_execute(
        sql,
        {
            "team_id": team_id,
            "event_name": leaf.event_name,
            "window_start": window_start,
            "at": at,
            "op_value": leaf.op_value,
        },
        settings=_MEMBER_SET_SETTINGS,
        workload=Workload.OFFLINE,
        team_id=team_id,
    )
    return {str(row[0]).lower() for row in rows}


def load_day_counts(
    team_id: int,
    *,
    event_name: str,
    person_ids: Sequence[str],
    scan_start: datetime,
    at: datetime,
    grace_start: datetime,
    boundary_at: datetime,
    seg_tz: str,
) -> dict[str, list[DayMatch]]:
    """Per-(person, day, boundary-bucket) match counts over ``person_ids`` (missing ∪ false members).

    ``day`` is bucketed in ``seg_tz`` (the run tz, to align with confirmed chunk days). The scan starts
    one calendar day before the window so the eviction-pending split can see the just-slid-out day.
    """
    if not person_ids:
        return {}
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    sql = _SEGMENTATION_SQL.format(overrides_join=_OVERRIDES_JOIN)
    counts: dict[str, list[DayMatch]] = defaultdict(list)
    ids = list(person_ids)
    for start in range(0, len(ids), _SEGMENTATION_CHUNK):
        chunk = ids[start : start + _SEGMENTATION_CHUNK]
        rows = sync_execute(
            sql,
            {
                "team_id": team_id,
                "event_name": event_name,
                "seg_tz": seg_tz,
                "grace_start": grace_start,
                "boundary_at": boundary_at,
                "scan_start": scan_start,
                "at": at,
                "person_ids": chunk,
            },
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
        for person_id, day, bucket, matches in rows:
            counts[str(person_id).lower()].append(DayMatch(day=day, bucket=str(bucket), matches=int(matches)))
    return dict(counts)


def load_run_context(team_id: int, cohort_id: int, run_id: Optional[str] = None) -> Optional[RunContext]:
    """The backfill run the missing set is segmented against.

    B5 is absent, so real runs stay ``seeding`` forever — deliberately no status filter. Accepts the
    latest run the cohort participates in (or the explicit ``run_id``) with a set ``boundary_at``.
    """
    runs = (
        CohortBackfillRun.objects.for_team(team_id)
        .filter(run_cohorts__cohort_id=cohort_id, boundary_at__isnull=False)
        .order_by("-created_at")
        .distinct()
    )
    run = runs.filter(id=run_id).first() if run_id else runs.first()
    if run is None or run.boundary_at is None:
        return None

    # run_cohorts / chunks are fail-closed reverse relations, so query them through for_team rather
    # than the run's default (team-scoped) manager, which raises outside a request/team context.
    participation = CohortBackfillRunCohort.objects.for_team(team_id).filter(run_id=run.id, cohort_id=cohort_id).first()
    participation_hash = participation.behavioral_filters_shape_hash if participation else ""
    current_hash = (
        Cohort.objects.filter(id=cohort_id, team_id=team_id)
        .values_list("behavioral_filters_shape_hash", flat=True)
        .first()
    ) or ""

    # A day is a confirmed seed domain only when all of its band chunks are CONFIRMED — a partially
    # seeded day must not let a missing person be blamed on the seeder (a false FAIL).
    chunks = CohortBackfillChunk.objects.for_team(team_id).filter(run_id=run.id)
    day_statuses: dict[date, set[str]] = defaultdict(set)
    for day, status in chunks.values_list("day", "status"):
        day_statuses[day].add(status)
    confirmed_days = frozenset(
        day for day, statuses in day_statuses.items() if statuses == {CohortBackfillChunkStatus.CONFIRMED}
    )
    non_confirmed = chunks.exclude(status=CohortBackfillChunkStatus.CONFIRMED).count()

    run_tz = resolve_zoneinfo(run.timezone)
    return RunContext(
        run_id=str(run.id),
        status=run.status,
        boundary_at=run.boundary_at,
        run_timezone=run.timezone,
        boundary_day=day_of_instant(run.boundary_at, run_tz),
        confirmed_days=confirmed_days,
        non_confirmed_chunks=non_confirmed,
        shape_hash_drift=participation_hash != current_hash,
    )
