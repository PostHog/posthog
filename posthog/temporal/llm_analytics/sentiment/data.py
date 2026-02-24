"""Data access for sentiment classification.

Fetches $ai_generation events from ClickHouse via HogQL and groups
results by trace_id for downstream processing.
"""

import json

from posthog.temporal.llm_analytics.sentiment.constants import (
    GENERATIONS_QUERY,
    MAX_GENERATIONS_PER_TRACE,
    MAX_INPUT_BYTES,
    MIN_INPUT_BYTES,
)


def fetch_generations(
    team_id: int,
    trace_ids: list[str],
    date_from: str,
    date_to: str,
) -> dict[str, list[tuple[str, object]]]:
    """Fetch $ai_generation events and group by trace_id.

    Returns {trace_id: [(event_uuid, ai_input), ...]} with at most
    MAX_GENERATIONS_PER_TRACE rows per trace. The query uses a window
    function for per-trace limiting and size filters to skip tool calls
    and accumulated conversation histories.
    """
    from posthog.hogql import ast
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.models.team import Team

    team = Team.objects.get(id=team_id)
    query = parse_select(GENERATIONS_QUERY)
    result = execute_hogql_query(
        query_type="SentimentOnDemand",
        query=query,
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "trace_ids": ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_ids]),
            "min_input_bytes": ast.Constant(value=MIN_INPUT_BYTES),
            "max_input_bytes": ast.Constant(value=MAX_INPUT_BYTES),
            "max_gens_per_trace": ast.Constant(value=MAX_GENERATIONS_PER_TRACE),
        },
        team=team,
        limit_context=LimitContext.QUERY_ASYNC,
    )

    rows_by_trace: dict[str, list[tuple[str, object]]] = {}
    for row in result.results or []:
        row_trace_id = str(row[2])
        raw_ai_input = row[1]
        ai_input = json.loads(raw_ai_input) if isinstance(raw_ai_input, str) else raw_ai_input
        rows_by_trace.setdefault(row_trace_id, []).append((str(row[0]), ai_input))

    return rows_by_trace
