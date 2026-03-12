"""Temporal activity for sentiment classification.

Fetches $ai_generation events, extracts user messages, and classifies
sentiment via the ONNX model. Supports both trace-level and generation-level
analysis, controlled by `analysis_level` on the input.
"""

import time
import asyncio
from typing import Any

import structlog
import temporalio

from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentInput, PendingClassification
from posthog.temporal.llm_analytics.sentiment.utils import (
    build_generation_result,
    build_trace_result,
    collect_pending,
    resolve_date_bounds,
)

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def classify_sentiment_activity(input: ClassifySentimentInput) -> dict[str, dict[str, Any]]:
    """Classify sentiment for traces or individual generations.

    When analysis_level="trace", fetches all generations per trace and
    builds trace-level aggregated results.
    When analysis_level="generation", fetches specific events by UUID
    and builds per-generation results.
    """
    from posthog.sync import database_sync_to_async
    from posthog.temporal.llm_analytics.sentiment.constants import MAX_CLASSIFICATIONS_PER_TRACE
    from posthog.temporal.llm_analytics.sentiment.data import fetch_generations, fetch_generations_by_uuid
    from posthog.temporal.llm_analytics.sentiment.metrics import (
        record_generations_classified,
        record_generations_fetched,
        record_inference_time_ms,
        record_messages_classified,
        record_query_time_ms,
        record_traces_classified,
    )
    from posthog.temporal.llm_analytics.sentiment.model import classify

    resolved_from, resolved_to = resolve_date_bounds(input.date_from, input.date_to)
    is_generation = input.analysis_level == "generation"

    # 1. Fetch — different query and grouping per level
    t0 = time.monotonic()
    if is_generation:
        rows, total_input_bytes = await database_sync_to_async(
            lambda: fetch_generations_by_uuid(input.team_id, input.ids, resolved_from, resolved_to),
            thread_sensitive=False,
        )()
        rows_by_id: dict[str, list[tuple[str, object]]] = {}
        for event_uuid, ai_input in rows:
            rows_by_id.setdefault(event_uuid, []).append((event_uuid, ai_input))
        total_generations = len(rows)
    else:
        fetch = await database_sync_to_async(
            lambda: fetch_generations(input.team_id, input.ids, resolved_from, resolved_to),
            thread_sensitive=False,
        )()
        rows_by_id = fetch.rows_by_trace
        total_generations = sum(len(r) for r in rows_by_id.values())
        total_input_bytes = fetch.total_input_bytes
    query_ms = (time.monotonic() - t0) * 1000

    record_query_time_ms(query_ms)
    record_generations_fetched(total_generations)

    # 2. Collect pending — same for both levels
    pending: list[PendingClassification] = []
    for id_ in input.ids:
        pending.extend(collect_pending(rows_by_id.get(id_, []), id_, MAX_CLASSIFICATIONS_PER_TRACE))

    # 3. Classify — same for both levels
    t1 = time.monotonic()
    all_results = await asyncio.to_thread(classify, [p.text for p in pending]) if pending else []
    inference_ms = (time.monotonic() - t1) * 1000

    if pending:
        record_inference_time_ms(inference_ms)
        record_messages_classified(len(pending))

    # 4. Build results — different aggregation per level
    output: dict[str, dict[str, Any]] = {}
    per_gen_for_cache: dict[str, dict[str, dict[str, Any]]] = {}
    offset = 0
    for id_ in input.ids:
        if is_generation:
            gen_pending = [p for p in pending if p.gen_uuid == id_]
            gen_results = all_results[offset : offset + len(gen_pending)]
            output[id_] = build_generation_result(id_, gen_pending, gen_results)
            offset += len(gen_pending)
        else:
            trace_result, per_gen, consumed = build_trace_result(id_, pending, all_results, offset)
            output[id_] = trace_result.to_dict()
            per_gen_for_cache[id_] = per_gen
            offset += consumed

    if is_generation:
        record_generations_classified(len(output))
    else:
        record_traces_classified(len(input.ids))

    # 5. Cache — key format: llma_sentiment:{level}:{team_id}:{id}
    #    Trace level also dual-writes generation cache entries
    from django.core.cache import cache

    from posthog.temporal.llm_analytics.sentiment.constants import CACHE_KEY_PREFIX, CACHE_TTL

    def _cache_key(level: str, id_: str) -> str:
        return f"{CACHE_KEY_PREFIX}:{level}:{input.team_id}:{id_}"

    to_cache: dict[str, dict] = {}
    for id_, result in output.items():
        to_cache[_cache_key(input.analysis_level, id_)] = result
        if not is_generation:
            for gen_uuid, gen_data in per_gen_for_cache.get(id_, {}).items():
                to_cache[_cache_key("generation", gen_uuid)] = gen_data
    if to_cache:
        try:
            cache.set_many(to_cache, timeout=CACHE_TTL)
        except Exception:
            logger.warning(
                "Failed to cache sentiment results",
                team_id=input.team_id,
                trace_count=len(to_cache),
                exc_info=True,
            )

    logger.info(
        "Sentiment activity completed",
        team_id=input.team_id,
        analysis_level=input.analysis_level,
        id_count=len(input.ids),
        generations_fetched=total_generations,
        input_kb=round(total_input_bytes / 1024, 1) if total_input_bytes else 0,
        messages_classified=len(pending),
        query_ms=round(query_ms),
        inference_ms=round(inference_ms) if pending else 0,
    )

    return output
