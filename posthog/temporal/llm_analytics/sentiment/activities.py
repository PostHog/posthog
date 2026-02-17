"""Temporal activity for sentiment classification.

Fetches $ai_generation events, extracts user messages, and classifies
sentiment via the ONNX model for one or more traces in a single batch.
"""

import json
from typing import Any

import structlog
import temporalio

from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentInput, PendingClassification
from posthog.temporal.llm_analytics.sentiment.utils import build_trace_result, collect_pending, resolve_date_bounds

logger = structlog.get_logger(__name__)


_GENERATIONS_QUERY = """
    SELECT uuid, properties, properties.$ai_trace_id AS trace_id
    FROM events
    WHERE event = '$ai_generation'
      AND timestamp >= toDateTime({date_from}, 'UTC')
      AND timestamp <= toDateTime({date_to}, 'UTC')
      AND properties.$ai_trace_id IN {trace_ids}
    ORDER BY trace_id, timestamp DESC
    LIMIT {max_rows}
"""


@temporalio.activity.defn
async def classify_sentiment_activity(input: ClassifySentimentInput) -> dict[str, dict[str, Any]]:
    """Fetch $ai_generation events for traces and classify sentiment on user messages."""
    from posthog.hogql import ast
    from posthog.hogql.constants import LimitContext
    from posthog.hogql.parser import parse_select
    from posthog.hogql.query import execute_hogql_query

    from posthog.models.team import Team
    from posthog.sync import database_sync_to_async
    from posthog.temporal.llm_analytics.sentiment.constants import MAX_GENERATIONS, MAX_TOTAL_CLASSIFICATIONS
    from posthog.temporal.llm_analytics.sentiment.model import classify_batch

    resolved_from, resolved_to = resolve_date_bounds(input.date_from, input.date_to)

    def _fetch_generations():
        team = Team.objects.get(id=input.team_id)
        query = parse_select(_GENERATIONS_QUERY)
        return execute_hogql_query(
            query_type="SentimentOnDemand",
            query=query,
            placeholders={
                "date_from": ast.Constant(value=resolved_from),
                "date_to": ast.Constant(value=resolved_to),
                "trace_ids": ast.Tuple(exprs=[ast.Constant(value=tid) for tid in input.trace_ids]),
                "max_rows": ast.Constant(value=MAX_GENERATIONS * len(input.trace_ids)),
            },
            team=team,
            limit_context=LimitContext.QUERY_ASYNC,
        )

    result = await database_sync_to_async(_fetch_generations, thread_sensitive=False)()

    # Group rows by trace_id, enforcing per-trace generation limit
    rows_by_trace: dict[str, list[tuple[str, dict]]] = {}
    for row in result.results or []:
        row_trace_id = str(row[2])
        trace_rows = rows_by_trace.setdefault(row_trace_id, [])
        if len(trace_rows) < MAX_GENERATIONS:
            raw_props = row[1]
            props = json.loads(raw_props) if isinstance(raw_props, str) else raw_props
            trace_rows.append((str(row[0]), props))

    # Collect all texts to classify across all traces
    pending: list[PendingClassification] = []
    gen_uuids_seen: list[str] = []

    for trace_id in input.trace_ids:
        trace_pending, trace_gen_uuids = collect_pending(
            rows_by_trace.get(trace_id, []), trace_id, MAX_TOTAL_CLASSIFICATIONS
        )
        pending.extend(trace_pending)
        gen_uuids_seen.extend(trace_gen_uuids)

    # Batch classify all texts across all traces in one call
    all_results = classify_batch([p.text for p in pending]) if pending else []

    if pending:
        from posthog.temporal.llm_analytics.sentiment.metrics import (
            record_messages_classified,
            record_traces_classified,
        )

        record_traces_classified(len(input.trace_ids))
        record_messages_classified(len(pending))

    # Build per-trace results
    output: dict[str, dict[str, Any]] = {}
    offset = 0
    for trace_id in input.trace_ids:
        trace_result, consumed = build_trace_result(trace_id, pending, gen_uuids_seen, all_results, offset)
        output[trace_id] = trace_result
        offset += consumed

    return output
