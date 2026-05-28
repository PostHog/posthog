"""
Lazy precompute pipeline for retention queries.

This module is the foundation layer — it knows how to materialise the
`retention_actor_event_day` pre-agg table for a given (team, date range) but does
not yet wire the read path. The runner integration that decides "use pre-agg vs
raw events" arrives in a follow-up commit; until then this is dead code in
production and only exercised by tests and ad-hoc precompute calls.

The materialisation is shape-agnostic: every retention query for a team that
covers a given day reads the same materialised rows, regardless of the specific
target / return entity or breakdown. This is why the INSERT query has no
per-query placeholders — only the time window changes per job.

Design and sizing in `.planning/retention-preagg-prototype.md`.
"""

from __future__ import annotations

from datetime import datetime

from posthog.models import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    ensure_precomputed,
)

# TTL ladder. Today's window expires quickly because late-arriving events still
# need to land; older windows are stable and can be cached for a week. Mirrors
# the staleness model `ensure_precomputed` already supports for web analytics
# and matches the 24h "seal" semantics in the prototype design doc.
LAZY_TTL_SECONDS: dict[str, int] = {
    "0d": 15 * 60,  # current day: 15 min — late arrivals will trigger re-materialisation
    "1d": 60 * 60,  # yesterday: 1 hour
    "7d": 24 * 60 * 60,  # last week: 1 day
    "default": 7 * 24 * 60 * 60,  # older: 7 days
}


# HogQL INSERT template. The framework substitutes `time_window_min` /
# `time_window_max` per job, parses the result, and INSERTs into the target
# table. It automatically prepends `team_id`, `job_id` and appends `expires_at`
# so the SELECT here only emits the payload columns in their table order.
#
# `group_type_index = -1` hard-codes v1 to person retention. Group retention is
# a v2 expansion (the schema column is in place; the materialisation just needs
# to iterate `group_type_index` and emit `$group_N` for each).
#
# `event` is captured as-is from raw events; the LowCardinality(String) column
# on the target table handles the conversion. We do NOT filter by event name
# here — the read query will filter to the start/return entities it cares
# about, and the same row serves multiple retention queries against different
# entities for the same team-day.
INSERT_QUERY_TEMPLATE = """
SELECT
    toDate(toTimeZone(events.timestamp, 'UTC')) AS day,
    events.person_id AS actor_id,
    -1 AS group_type_index,
    events.event AS event,
    min(events.timestamp) AS first_ts
FROM events
WHERE events.timestamp >= {time_window_min}
    AND events.timestamp < {time_window_max}
GROUP BY day, actor_id, event
"""


def ensure_retention_precomputed(
    team: Team,
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    """Materialise the retention pre-agg table for the given team + window.

    The INSERT is partitioned into daily jobs by `ensure_precomputed` — each
    daily window writes its own `job_id` so re-materialisation of a single day
    (e.g. after a late event lands) doesn't redo the whole range. Reads filter
    by `job_id IN (result.job_ids)` to pick the latest set.

    `computed_at` is omitted from the SELECT — the table's `DEFAULT now()`
    fills it at INSERT time, matching the web analytics precompute precedent.
    The framework builds the INSERT's column list from the SELECT's aliases,
    so missing columns fall back to their table DEFAULT.
    """
    return ensure_precomputed(
        team=team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.RETENTION_ACTOR_EVENT_DAY,
        placeholders={},
        query_type="retention_actor_event_day",
    )


__all__ = [
    "INSERT_QUERY_TEMPLATE",
    "LAZY_TTL_SECONDS",
    "ensure_retention_precomputed",
]
