"""Resolve generation event UUIDs → parent trace_id via a small `events` lookup.

Used as a preflight before heavy-column reads on `ai_events`. The `ai_events`
sorting key `(team_id, trace_id, timestamp)` is useless for `WHERE uuid IN (...)`
queries that don't carry trace_id — they fan out across every shard via the
`cityHash64(team_id, trace_id, ...)` sharding key, then read heavy columns
(input, output, output_choices, ...) on each one. A bloom filter on `uuid`
helps with within-shard granule skipping but can't address the cross-shard
fan-out — only knowing trace_id can.

This helper does the trace_id discovery cheaply on the shared `events` table:
its sorting key `(team_id, toDate(timestamp), event, ...)` lets the scan be
narrowed by `(team, date_range, event='$ai_generation')`, and we project only
`properties.$ai_trace_id` (HogQL resolves to the materialized
`mat_$ai_trace_id` column on events). Small column read on a narrowed range
even when the row-level uuid filter has to scan.

Then the caller plugs the discovered trace_ids into the heavy-column query on
`ai_events` — getting the full sorting-key prefix `(team_id, trace_id,
timestamp)` plus single-shard pruning via the sharding key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context

if TYPE_CHECKING:
    from datetime import datetime

    from posthog.models.team import Team


def resolve_trace_ids_for_generation_uuids(
    team: Team,
    generation_uuids: list[str],
    ts_start: datetime,
    ts_end: datetime,
    *,
    query_type: str = "TraceIdResolveForHeavyFetch",
) -> dict[str, str]:
    """Map generation event UUIDs → parent trace_id by reading `events`.

    Returns `{uuid: trace_id}` for uuids whose trace_id was found. UUIDs
    without a known trace_id are silently dropped — the caller decides how
    to handle (e.g. skip the heavy fetch entirely, or fall back to a
    no-trace-id query).

    `ts_start` / `ts_end` are required and bound the events scan via the
    `toDate(timestamp)` sorting-key segment + partition pruning. Pass a
    window aligned with the eventual heavy-fetch window.
    """
    if not generation_uuids:
        return {}

    query = parse_select(
        """
        SELECT toString(uuid) AS uuid, properties.$ai_trace_id AS trace_id
        FROM events
        WHERE event = '$ai_generation'
            AND timestamp >= {ts_start}
            AND timestamp < {ts_end}
            AND toString(uuid) IN {uuids}
        """
    )

    with tags_context(product=Product.LLM_ANALYTICS):
        result = execute_hogql_query(
            query_type=query_type,
            query=query,
            placeholders={
                "ts_start": ast.Constant(value=ts_start),
                "ts_end": ast.Constant(value=ts_end),
                "uuids": ast.Array(exprs=[ast.Constant(value=u) for u in generation_uuids]),
            },
            team=team,
        )

    return {row[0]: row[1] for row in (result.results or []) if row[0] and row[1]}
