"""Data access for sentiment classification.

Fetches $ai_generation events from ClickHouse via HogQL and groups
results by trace_id for downstream processing.
"""

import json
from dataclasses import dataclass, field

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.temporal.llm_analytics.sentiment.constants import (
    GENERATIONS_BY_UUID_QUERY,
    GENERATIONS_QUERY,
    MAX_GENERATIONS_PER_TRACE,
    MAX_INPUT_CHARS,
    MAX_INPUT_CHARS_GENERATION,
)


@dataclass
class FetchResult:
    rows_by_trace: dict[str, list[tuple[str, object]]] = field(default_factory=dict)
    total_input_bytes: int = 0


def fetch_generations(
    team_id: int,
    trace_ids: list[str],
    date_from: str,
    date_to: str,
) -> FetchResult:
    """Fetch $ai_generation events and group by trace_id.

    Returns a FetchResult with rows grouped by trace_id (at most
    MAX_GENERATIONS_PER_TRACE per trace) and total raw input bytes
    transferred from ClickHouse.
    """
    from posthog.hogql import ast
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.parser import parse_select

    from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback
    from posthog.models.team import Team

    team = Team.objects.get(id=team_id)
    query = parse_select(GENERATIONS_QUERY)
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team_id):
        result = execute_with_ai_events_fallback(
            query=query,
            placeholders={
                "date_from": ast.Constant(value=date_from),
                "date_to": ast.Constant(value=date_to),
                "trace_ids": ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_ids]),
                "max_input_chars": ast.Constant(value=MAX_INPUT_CHARS),
                "max_gens_per_trace": ast.Constant(value=MAX_GENERATIONS_PER_TRACE),
            },
            team=team,
            query_type="SentimentOnDemand",
            limit_context=LimitContext.QUERY_ASYNC,
        )

    fetch = FetchResult()
    for row in result.results or []:
        row_trace_id = str(row[2])
        raw_ai_input = row[1]
        if isinstance(raw_ai_input, str):
            fetch.total_input_bytes += len(raw_ai_input.encode("utf-8"))
            try:
                ai_input = json.loads(raw_ai_input)
            except (json.JSONDecodeError, ValueError):
                continue
        else:
            ai_input = raw_ai_input
        fetch.rows_by_trace.setdefault(row_trace_id, []).append((str(row[0]), ai_input))

    return fetch


def fetch_generations_by_uuid(
    team_id: int,
    generation_ids: list[str],
    date_from: str,
    date_to: str,
) -> tuple[list[tuple[str, object]], int]:
    """Fetch specific $ai_generation events by UUID.

    Simpler than fetch_generations — no window function, no trace grouping.
    Returns a flat list of (uuid, ai_input) tuples.

    Uses a two-query pattern: the `(team_id, trace_id, timestamp)` sorting
    key + cityHash64 sharding key on `ai_events` mean a `WHERE uuid IN (...)`
    fan-out reads heavy `input` on every shard. So we first resolve uuid →
    trace_id off `events` (cheap small-column read using the events sorting
    key) and pass the resulting trace_ids into the heavy fetch — keeping
    the heavy read on a single shard.
    """
    from datetime import UTC, datetime

    from posthog.hogql import ast
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.parser import parse_select

    from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback
    from posthog.hogql_queries.ai.trace_id_resolver import resolve_trace_ids_for_generation_uuids
    from posthog.models.team import Team

    team = Team.objects.get(id=team_id)

    # `date_from` / `date_to` arrive as `%Y-%m-%d %H:%M:%S` strings (per
    # `resolve_date_bounds`). Parse them to UTC datetimes so the trace-id
    # resolver can serialize them through HogQL placeholder substitution.
    ts_start = datetime.strptime(date_from, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    ts_end = datetime.strptime(date_to, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)

    trace_id_by_uuid = resolve_trace_ids_for_generation_uuids(
        team=team,
        generation_uuids=generation_ids,
        ts_start=ts_start,
        ts_end=ts_end,
        query_type="SentimentTraceIdResolve",
    )
    trace_ids = sorted({tid for tid in trace_id_by_uuid.values() if tid})
    if not trace_ids:
        return [], 0

    query = parse_select(GENERATIONS_BY_UUID_QUERY)
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.QUERY, team_id=team_id):
        result = execute_with_ai_events_fallback(
            query=query,
            placeholders={
                "date_from": ast.Constant(value=date_from),
                "date_to": ast.Constant(value=date_to),
                "uuids": ast.Tuple(exprs=[ast.Constant(value=uid) for uid in generation_ids]),
                "trace_ids": ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_ids]),
            },
            team=team,
            query_type="SentimentOnDemandGeneration",
            limit_context=LimitContext.QUERY_ASYNC,
        )

    # Size guard applied post-fetch instead of in SQL — the SQL length()
    # filter forced JSONExtractRaw on every scanned row, 2.4x slower on
    # high-volume teams. Here we just skip before json.loads to avoid
    # wasting time parsing huge payloads we'll mostly discard anyway.
    rows: list[tuple[str, object]] = []
    total_input_bytes = 0
    for row in result.results or []:
        raw_ai_input = row[1]
        if isinstance(raw_ai_input, str):
            if len(raw_ai_input) > MAX_INPUT_CHARS_GENERATION:
                continue
            total_input_bytes += len(raw_ai_input.encode("utf-8"))
            try:
                ai_input = json.loads(raw_ai_input)
            except (json.JSONDecodeError, ValueError):
                continue
        else:
            ai_input = raw_ai_input
        rows.append((str(row[0]), ai_input))

    return rows, total_input_bytes
