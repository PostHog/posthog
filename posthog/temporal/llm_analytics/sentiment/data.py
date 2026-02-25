"""Data access for sentiment classification.

Fetches $ai_generation events from ClickHouse via HogQL and groups
results by trace_id for downstream processing.
"""

import json
from dataclasses import dataclass, field

from posthog.temporal.llm_analytics.sentiment.constants import (
    GENERATIONS_QUERY,
    MAX_GENERATIONS_PER_TRACE,
    MAX_INPUT_CHARS,
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
            "max_input_chars": ast.Constant(value=MAX_INPUT_CHARS),
            "max_gens_per_trace": ast.Constant(value=MAX_GENERATIONS_PER_TRACE),
        },
        team=team,
        limit_context=LimitContext.QUERY_ASYNC,
    )

    fetch = FetchResult()
    for row in result.results or []:
        row_trace_id = str(row[2])
        raw_ai_input = row[1]
        if isinstance(raw_ai_input, str):
            fetch.total_input_bytes += len(raw_ai_input.encode("utf-8"))
            ai_input = json.loads(raw_ai_input)
        else:
            ai_input = raw_ai_input
        fetch.rows_by_trace.setdefault(row_trace_id, []).append((str(row[0]), ai_input))

    return fetch
