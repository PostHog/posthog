"""Recompute-oracle reads: ClickHouse member-set / segmentation queries + the Django run context.

Mixed IO (ClickHouse + ORM), precedented by :mod:`.snapshots`. The pure classification of what these
return lives in :mod:`.recompute`; this module only fetches.

Person resolution mirrors the seeder's overrides join (``rust/cohort-seeder/src/clickhouse/sql.rs``):
``if(notEmpty(ov.distinct_id), ov.person_id, e.person_id)`` with ``argMax(person_id, version) …
HAVING argMax(is_deleted, version) = 0`` from ``person_distinct_id_overrides``. Every read also
carries the seeder's ingestion cutoff — ``coalesce(e.inserted_at, e._timestamp) <= at`` — so the
oracle only counts events the pipeline could already have consumed by ``at``. Without it, ingestion
lag reads as an under-count the day-domain segmentation would blame on the seeder, and re-running at
a fixed ``--at`` would keep growing the oracle set.

All tz-date arithmetic is Python-side (:mod:`.tzdates`); SQL only ever compares ``e.timestamp``
against UTC datetime params or converts the ``e.timestamp`` *column* via
``toDate(<column>, %(team_tz)s)`` — never ``toDate(<param>, tz)``. Person ids are lowercased at the
boundary to match the fold's normalization (see ``fold.py``).
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

# The seeder's overrides join, shared by all three reads.
_OVERRIDES_JOIN = """
    LEFT JOIN (
        SELECT distinct_id, argMax(person_id, version) AS person_id
        FROM person_distinct_id_overrides
        WHERE team_id = %(team_id)s
        GROUP BY distinct_id
        HAVING argMax(is_deleted, version) = 0
    ) AS ov ON e.distinct_id = ov.distinct_id
"""

_RESOLVED_PERSON = "toString(if(notEmpty(ov.distinct_id), ov.person_id, e.person_id))"

_MEMBER_SET_SQL = """
SELECT resolved_person_id, count() AS match_count
FROM (
    SELECT {resolved_person} AS resolved_person_id
    FROM events AS e{overrides_join}
    WHERE e.team_id = %(team_id)s
      AND e.event = %(event_name)s
      AND e.timestamp >= %(window_start)s
      AND e.timestamp <= %(at)s
      AND coalesce(e.inserted_at, e._timestamp) <= %(at)s
)
GROUP BY resolved_person_id
HAVING match_count >= 1 AND match_count {op} %(op_value)s
LIMIT %(limit)s
"""

_LEAF_COUNTS_SQL = """
SELECT {resolved_person} AS resolved_person_id, count() AS matches
FROM events AS e{overrides_join}
WHERE e.team_id = %(team_id)s
  AND e.event = %(event_name)s
  AND e.timestamp >= %(window_start)s
  AND e.timestamp <= %(at)s
  AND coalesce(e.inserted_at, e._timestamp) <= %(at)s
  AND {resolved_person} IN %(person_ids)s
GROUP BY resolved_person_id
"""

_SEGMENTATION_SQL = """
SELECT {resolved_person} AS resolved_person_id,
       toDate(e.timestamp, %(team_tz)s) AS day,
       multiIf(e.timestamp >= %(grace_start)s, 'grace',
               e.timestamp >= %(boundary_at)s, 'post_boundary',
               'pre_boundary') AS bucket,
       count() AS matches
FROM events AS e{overrides_join}
WHERE e.team_id = %(team_id)s
  AND e.event = %(event_name)s
  AND e.timestamp >= %(scan_start)s
  AND e.timestamp <= %(at)s
  AND coalesce(e.inserted_at, e._timestamp) <= %(at)s
  AND {resolved_person} IN %(person_ids)s
GROUP BY resolved_person_id, day, bucket
"""

# The GROUP BY resolved_person_id can be large for a broad event; spill like the old-membership read.
_MEMBER_SET_SETTINGS = {
    "max_bytes_ratio_before_external_group_by": 0.5,
    "distributed_aggregation_memory_efficient": 1,
}

_PERSON_ID_CHUNK = 1000


class OracleSetTooLarge(Exception):
    """A leaf's member set exceeded the cap, so the oracle refuses to materialize it in memory."""

    def __init__(self, event_name: str, limit: int) -> None:
        super().__init__(f"leaf {event_name!r} matches more than {limit} persons")
        self.event_name = event_name
        self.limit = limit


def _render(sql: str, **extra: str) -> str:
    return sql.format(overrides_join=_OVERRIDES_JOIN, resolved_person=_RESOLVED_PERSON, **extra)


def load_leaf_members(team_id: int, leaf: OracleLeaf, *, at: datetime, tz: ZoneInfo, limit: int) -> set[str]:
    """Persons matching one leaf's ``count >= 1 AND op(count)`` predicate over its whole-day window.

    The whole set is materialized in memory, so it is capped: a broad event over a long window can
    match tens of millions of persons, which the driver would buffer and the Python set would not
    survive. Exceeding ``limit`` raises :class:`OracleSetTooLarge` rather than silently truncating.
    """
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    rows = sync_execute(
        _render(_MEMBER_SET_SQL, op=_OP_SQL[leaf.op]),
        {
            "team_id": team_id,
            "event_name": leaf.event_name,
            "window_start": window_start_utc(at, leaf.window_days, tz),
            "at": at,
            "op_value": leaf.op_value,
            "limit": limit + 1,
        },
        settings=_MEMBER_SET_SETTINGS,
        workload=Workload.OFFLINE,
        team_id=team_id,
    )
    if len(rows) > limit:
        raise OracleSetTooLarge(leaf.event_name, limit)
    return {str(row[0]).lower() for row in rows}


def load_leaf_match_counts(
    team_id: int,
    leaf: OracleLeaf,
    *,
    person_ids: Sequence[str],
    at: datetime,
    tz: ZoneInfo,
    extra_days: int,
) -> dict[str, int]:
    """Per-person match counts for one leaf over its window slid back ``extra_days``.

    Feeds the over-count eviction split: a person still satisfying every leaf's predicate under the
    just-slid-out window is due for eviction but not yet swept, not over-included.
    """
    if not person_ids:
        return {}
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    sql = _render(_LEAF_COUNTS_SQL)
    window_start = window_start_utc(at, leaf.window_days + extra_days, tz)
    counts: dict[str, int] = {}
    for chunk in _chunks(person_ids):
        rows = sync_execute(
            sql,
            {
                "team_id": team_id,
                "event_name": leaf.event_name,
                "window_start": window_start,
                "at": at,
                "person_ids": chunk,
            },
            workload=Workload.OFFLINE,
            team_id=team_id,
        )
        for person_id, matches in rows:
            counts[str(person_id).lower()] = int(matches)
    return counts


def load_day_counts(
    team_id: int,
    *,
    event_name: str,
    person_ids: Sequence[str],
    scan_start: datetime,
    at: datetime,
    grace_start: datetime,
    boundary_at: datetime,
    team_tz: str,
) -> dict[str, list[DayMatch]]:
    """Per-(person, day, boundary-bucket) match counts over the missing set.

    ``day`` is bucketed in the team tz — the only tz the processor ever uses for day boundaries
    (``event_path.rs`` reads ``filters.timezone``), so the day set the oracle window covers and the
    days attributed to seed chunks are the same days.
    """
    if not person_ids:
        return {}
    tag_queries(product=ProductKey.COHORTS, feature=Feature.COHORT)
    sql = _render(_SEGMENTATION_SQL)
    counts: dict[str, list[DayMatch]] = defaultdict(list)
    for chunk in _chunks(person_ids):
        rows = sync_execute(
            sql,
            {
                "team_id": team_id,
                "event_name": event_name,
                "team_tz": team_tz,
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


def _chunks(person_ids: Sequence[str]) -> list[list[str]]:
    ids = list(person_ids)
    return [ids[start : start + _PERSON_ID_CHUNK] for start in range(0, len(ids), _PERSON_ID_CHUNK)]


def load_run_context(team_id: int, cohort_id: int, run_id: Optional[str] = None) -> Optional[RunContext]:
    """The backfill run the missing set is segmented against.

    B5 is absent, so real runs stay ``seeding`` forever — deliberately no status filter. Accepts the
    latest run the cohort participates in (or the explicit ``run_id``) with a set ``boundary_at``.
    Returns ``None`` when there is no such run; an explicitly requested ``run_id`` that does not
    resolve is the caller's error to raise, not a silent downgrade to an unsegmented report.
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
