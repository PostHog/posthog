"""Materialise the per-actor retention table (page-view + all-events scope).

Fills `retention_actor` for a (team, kind) by scanning the team's event history and writing,
per actor, two aggregate states: `minState` of their first qualifying timestamp and a
`groupUniqArrayState` of the absolute day-numbers (team-tz `toDate`) they were active, capped
to a horizon from the first day.

v1 strategy: full re-derivation. `AggregatingMergeTree` merges the states idempotently — a
re-run re-inserts each actor's state and `min` / set-union absorb it — so re-materialising is
safe and never double-counts. Freshness is tracked in Redis (the table has no `computed_at`),
and a Redis lock stops concurrent readers stampeding the same scan.

The INSERT is raw SQL (not HogQL) so the `AggregateFunction` argument types match the column
types exactly and the team-tz `toDate` day-numbers line up with the read path.

Person overrides are resolved at INSERT time by the same `distinct_id` join the raw read path
uses (`person_distinct_id_overrides`, latest non-deleted `person_id` per distinct_id). The
INSERT runs on the main cluster where `events` and the override table are colocated, so the
join is local; only the write lands on AUX. This is the web-analytics pre-agg pattern — a merge
that lands *after* a materialisation is reconciled on the next rebuild, not at read time (the
stored key is `person_id` and the live override mapping is `distinct_id`-keyed, so read-time
person-grained resolution is not available).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.preaggregation.retention_actor_sql import ALL_EVENTS_KIND, DISTRIBUTED_RETENTION_ACTOR_TABLE
from posthog.models import Team
from posthog.redis import get_client

logger = structlog.get_logger(__name__)

PAGEVIEW_KIND = "$pageview"
SUPPORTED_KINDS = (PAGEVIEW_KIND, ALL_EVENTS_KIND)

# Max day-offset from the actor's first day that we store. Bounds per-actor state and caps the
# lookahead the table can serve; longer-lookahead queries fall through to raw at the gate.
HORIZON_DAYS = 800

# How long a materialised (team, kind) is treated as fresh. Recent activity isn't reflected
# until the next run; older cohorts are immutable, so this only bounds recent-cohort staleness.
STALENESS_SECONDS = 15 * 60

_LOCK_TIMEOUT_SECONDS = 10 * 60
# Short, so a query contending on a concurrent build falls back to raw quickly instead of hanging.
_LOCK_BLOCKING_TIMEOUT_SECONDS = 5
_INSERT_MAX_EXECUTION_TIME_SECONDS = 5 * 60

# initializeAggregation('minState', ts) and arrayReduce('groupUniqArrayState', days) build the
# AggregateFunction states per row from scalars, so no outer GROUP BY is needed. The horizon
# filter drops day-numbers more than HORIZON_DAYS past the actor's first day. The inner query
# resolves person overrides via the distinct_id join (latest non-deleted person_id per
# distinct_id) and groups by the resolved actor, so merged people collapse to one row.
_INSERT_TEMPLATE = """
INSERT INTO {table} (team_id, kind, actor_id, first_seen, active_days)
SELECT
    %(team_id)s,
    %(kind)s,
    actor_id,
    initializeAggregation('minState', min_ts),
    arrayReduce(
        'groupUniqArrayState',
        arrayFilter(dn -> dn - arrayMin(day_nums) <= %(horizon)s, day_nums)
    )
FROM (
    SELECT
        if(empty(o.distinct_id), e.person_id, o.person_id) AS actor_id,
        min(e.timestamp) AS min_ts,
        groupUniqArray(toUInt32(toDate(e.timestamp, %(tz)s))) AS day_nums
    FROM events AS e
    LEFT JOIN (
        SELECT
            distinct_id,
            argMax(person_id, version) AS person_id
        FROM person_distinct_id_overrides
        WHERE team_id = %(team_id)s
        GROUP BY distinct_id
        HAVING argMax(is_deleted, version) = 0
    ) AS o ON e.distinct_id = o.distinct_id
    WHERE e.team_id = %(team_id)s AND {event_filter} AND e.timestamp <= now()
    GROUP BY actor_id
)
"""

_FRESHNESS_KEY = "retention_actor:materialized_at:{team_id}:{kind}"
# Redis freshness marker outlives the staleness window so a still-fresh table isn't re-scanned
# just because the marker expired.
_FRESHNESS_TTL_SECONDS = STALENESS_SECONDS * 4


@dataclass
class RetentionActorMaterialisation:
    ready: bool


def kind_for_entity_id(entity_id: str | float | None) -> str:
    """Map a retention entity id to the stored `kind`: the all-events entity (`None`) → the
    marker, otherwise the raw event name."""
    return ALL_EVENTS_KIND if entity_id is None else str(entity_id)


def _event_filter_sql(kind: str) -> str:
    # The all-events marker matches every event; any other kind is a real event name (e.g. the
    # `kind` column value itself), bound as a parameter — so a new SUPPORTED_KINDS entry filters
    # on its own event instead of silently matching everything.
    return "1 = 1" if kind == ALL_EVENTS_KIND else "e.event = %(event_name)s"


def materialize_retention_actor(team: Team, kind: str) -> None:
    """Re-derive a (team, kind)'s actor states from event history. Idempotent — the
    AggregateFunction states merge on read."""
    if kind not in SUPPORTED_KINDS:
        raise ValueError(f"Unsupported retention_actor kind: {kind!r} (expected one of {SUPPORTED_KINDS})")

    sql = _INSERT_TEMPLATE.format(
        table=DISTRIBUTED_RETENTION_ACTOR_TABLE(),
        event_filter=_event_filter_sql(kind),
    )
    sync_execute(
        sql,
        {"team_id": team.pk, "kind": kind, "event_name": kind, "horizon": HORIZON_DAYS, "tz": team.timezone},
        # Wait for the write to land on the AUX shard before marking fresh — otherwise a reader can
        # see the freshness marker and query a partially-populated table. Safe here because we
        # insert the small per-actor aggregate, not the raw event scan.
        settings={"max_execution_time": _INSERT_MAX_EXECUTION_TIME_SECONDS, "insert_distributed_sync": 1},
    )
    get_client().set(
        _FRESHNESS_KEY.format(team_id=team.pk, kind=kind),
        datetime.now(UTC).isoformat(),
        ex=_FRESHNESS_TTL_SECONDS,
    )


def _is_fresh(team: Team, kind: str) -> bool:
    raw = get_client().get(_FRESHNESS_KEY.format(team_id=team.pk, kind=kind))
    if raw is None:
        return False
    materialized_at = datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw)
    return datetime.now(UTC) - materialized_at < timedelta(seconds=STALENESS_SECONDS)


def ensure_retention_actor(team: Team, kind: str) -> RetentionActorMaterialisation:
    """Ensure a fresh (team, kind) materialisation exists, building it if stale. Returns
    `ready=False` for unsupported kinds or on failure — the read path treats this as a hint and
    falls through to raw events."""
    if kind not in SUPPORTED_KINDS:
        return RetentionActorMaterialisation(ready=False)

    if _is_fresh(team, kind):
        return RetentionActorMaterialisation(ready=True)

    lock = get_client().lock(
        f"retention_actor:materialize:{team.pk}:{kind}",
        timeout=_LOCK_TIMEOUT_SECONDS,
        blocking_timeout=_LOCK_BLOCKING_TIMEOUT_SECONDS,
    )
    if not lock.acquire():
        return RetentionActorMaterialisation(ready=_is_fresh(team, kind))

    try:
        if _is_fresh(team, kind):
            return RetentionActorMaterialisation(ready=True)
        materialize_retention_actor(team, kind)
        return RetentionActorMaterialisation(ready=True)
    except Exception as e:
        logger.exception("retention_actor.materialise_failed", team_id=team.pk, kind=kind, error=str(e))
        return RetentionActorMaterialisation(ready=False)
    finally:
        try:
            lock.release()
        except Exception:
            pass


__all__ = [
    "ALL_EVENTS_KIND",
    "HORIZON_DAYS",
    "PAGEVIEW_KIND",
    "SUPPORTED_KINDS",
    "RetentionActorMaterialisation",
    "ensure_retention_actor",
    "kind_for_entity_id",
    "materialize_retention_actor",
]
