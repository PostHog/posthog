"""Temporal activity for sentiment classification.

Fetches $ai_generation events, extracts user messages, and classifies
sentiment via the ONNX model for one or more traces in a single batch.
"""

import time
import asyncio
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
    from posthog.temporal.llm_analytics.sentiment.constants import MAX_CLASSIFICATIONS_PER_TRACE
    from posthog.temporal.llm_analytics.sentiment.data import fetch_generations
    from posthog.temporal.llm_analytics.sentiment.metrics import (
        record_generations_fetched,
        record_inference_time_ms,
        record_messages_classified,
        record_query_time_ms,
        record_traces_classified,
    )
    from posthog.temporal.llm_analytics.sentiment.model import classify

    resolved_from, resolved_to = resolve_date_bounds(input.date_from, input.date_to)

    t0 = time.monotonic()
    fetch = await database_sync_to_async(
        lambda: fetch_generations(input.team_id, input.trace_ids, resolved_from, resolved_to),
        thread_sensitive=False,
    )()
    query_ms = (time.monotonic() - t0) * 1000

    total_generations = sum(len(rows) for rows in fetch.rows_by_trace.values())
    record_query_time_ms(query_ms)
    record_generations_fetched(total_generations)

    # Collect all texts to classify across all traces
    pending: list[PendingClassification] = []
    for trace_id in input.trace_ids:
        pending.extend(collect_pending(fetch.rows_by_trace.get(trace_id, []), trace_id, MAX_CLASSIFICATIONS_PER_TRACE))

    # Batch classify all texts across all traces in one call
    t1 = time.monotonic()
    all_results = await asyncio.to_thread(classify, [p.text for p in pending]) if pending else []
    inference_ms = (time.monotonic() - t1) * 1000

    if pending:
        record_inference_time_ms(inference_ms)
        record_traces_classified(len(input.trace_ids))
        record_messages_classified(len(pending))

    # Build per-trace results
    output: dict[str, dict[str, Any]] = {}
    offset = 0
    for trace_id in input.trace_ids:
        trace_result, consumed = build_trace_result(trace_id, pending, all_results, offset)
        output[trace_id] = trace_result.to_dict()
        offset += consumed

    logger.info(
        "Sentiment activity completed",
        team_id=input.team_id,
        trace_count=len(input.trace_ids),
        generations_fetched=total_generations,
        input_kb=round(fetch.total_input_bytes / 1024, 1),
        messages_classified=len(pending),
        query_ms=round(query_ms),
        inference_ms=round(inference_ms) if pending else 0,
    )

    return output
