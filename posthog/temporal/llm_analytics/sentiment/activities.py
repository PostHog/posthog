"""Temporal activity for sentiment classification.

Fetches $ai_generation events, extracts user messages, and classifies
sentiment via the ONNX model for one or more traces in a single batch.
"""

from typing import Any

import structlog
import temporalio

from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentInput, PendingClassification
from posthog.temporal.llm_analytics.sentiment.utils import build_trace_result, collect_pending, resolve_date_bounds

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def classify_sentiment_activity(input: ClassifySentimentInput) -> dict[str, dict[str, Any]]:
    """Fetch $ai_generation events for traces and classify sentiment on user messages."""
    from posthog.sync import database_sync_to_async
    from posthog.temporal.llm_analytics.sentiment.constants import MAX_TOTAL_CLASSIFICATIONS
    from posthog.temporal.llm_analytics.sentiment.data import fetch_generations
    from posthog.temporal.llm_analytics.sentiment.model import classify_batch

    resolved_from, resolved_to = resolve_date_bounds(input.date_from, input.date_to)

    rows_by_trace = await database_sync_to_async(
        lambda: fetch_generations(input.team_id, input.trace_ids, resolved_from, resolved_to),
        thread_sensitive=False,
    )()

    # Collect all texts to classify across all traces
    pending: list[PendingClassification] = []
    for trace_id in input.trace_ids:
        pending.extend(collect_pending(rows_by_trace.get(trace_id, []), trace_id, MAX_TOTAL_CLASSIFICATIONS))

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
        trace_result, consumed = build_trace_result(trace_id, pending, all_results, offset)
        output[trace_id] = trace_result
        offset += consumed

    return output
