"""Compute aggregate metrics (cost, latency, tokens, errors, sentiment) for clusters.

This activity is best-effort: it runs with a time budget and returns whatever
it managed to compute. Partial results (e.g., metrics without sentiment) are
perfectly fine — the frontend falls back to runtime loading for missing data.
"""

import time
import uuid
import asyncio
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils.dateparse import parse_datetime

import structlog
from temporalio import activity
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models.team import Team
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.sentiment.constants import (
    CACHE_KEY_PREFIX as SENTIMENT_CACHE_KEY_PREFIX,
    MAX_RETRY_ATTEMPTS as SENTIMENT_MAX_RETRY_ATTEMPTS,
    WORKFLOW_NAME as SENTIMENT_WORKFLOW_NAME,
    WORKFLOW_TIMEOUT_BATCH_SECONDS as SENTIMENT_WORKFLOW_TIMEOUT,
)
from posthog.temporal.llm_analytics.sentiment.schema import ClassifySentimentInput
from posthog.temporal.llm_analytics.trace_clustering.constants import (
    SENTIMENT_BATCH_SIZE,
    SENTIMENT_MAX_CONCURRENT,
    SENTIMENT_PER_BATCH_TIMEOUT,
    SENTIMENT_TOTAL_TIMEOUT,
)
from posthog.temporal.llm_analytics.trace_clustering.data import ItemMetrics, fetch_item_metrics
from posthog.temporal.llm_analytics.trace_clustering.models import (
    AnalysisLevel,
    ClusterAggregateMetrics,
    ClusterItem,
    ClusterSentiment,
    ComputeAggregatesActivityInputs,
)

logger = structlog.get_logger(__name__)


def _get_item_id(item: ClusterItem) -> str:
    return item.generation_id if item.generation_id else item.trace_id


def _aggregate_operational_metrics(
    items: list[ClusterItem],
    labels: list[int],
    item_metrics: dict[str, ItemMetrics],
) -> dict[int, ClusterAggregateMetrics]:
    """Aggregate cost/latency/tokens/errors per cluster from per-item metrics."""
    cluster_items: dict[int, list[str]] = {}
    for i, label in enumerate(labels):
        item_id = _get_item_id(items[i])
        cluster_items.setdefault(label, []).append(item_id)

    result: dict[int, ClusterAggregateMetrics] = {}
    for cluster_id, item_ids in cluster_items.items():
        total_cost = 0.0
        total_latency = 0.0
        total_tokens = 0
        cost_count = 0
        latency_count = 0
        token_count = 0
        items_with_errors = 0
        items_with_data = 0

        for item_id in item_ids:
            m = item_metrics.get(item_id)
            if not m:
                continue
            items_with_data += 1
            if m.error_count > 0:
                items_with_errors += 1
            if m.cost is not None and m.cost > 0:
                total_cost += m.cost
                cost_count += 1
            if m.latency is not None and m.latency > 0:
                total_latency += m.latency
                latency_count += 1
            tokens = (m.input_tokens or 0) + (m.output_tokens or 0)
            if tokens > 0:
                total_tokens += tokens
                token_count += 1

        result[cluster_id] = ClusterAggregateMetrics(
            avg_cost=total_cost / cost_count if cost_count > 0 else None,
            avg_latency=total_latency / latency_count if latency_count > 0 else None,
            avg_tokens=total_tokens / token_count if token_count > 0 else None,
            total_cost=total_cost if cost_count > 0 else None,
            error_rate=items_with_errors / items_with_data if items_with_data > 0 else None,
            error_count=items_with_errors,
            item_count=items_with_data,
        )

    return result


async def _fetch_sentiment_for_items(
    team_id: int,
    item_ids: list[str],
    analysis_level: AnalysisLevel,
    date_from: str,
    date_to: str,
) -> dict[str, dict]:
    """Fetch sentiment for items, using cache first, then Temporal workflows for misses."""
    from posthog.temporal.common.client import async_connect

    if not item_ids:
        return {}

    # Check cache first
    cache_keys = {id_: f"{SENTIMENT_CACHE_KEY_PREFIX}:{analysis_level}:{team_id}:{id_}" for id_ in item_ids}
    cached_values = await asyncio.to_thread(cache.get_many, list(cache_keys.values()))

    results: dict[str, dict] = {}
    misses: list[str] = []
    for id_ in item_ids:
        cached = cached_values.get(cache_keys[id_])
        if cached is not None:
            results[id_] = cached
        else:
            misses.append(id_)

    logger.info(
        "sentiment_cache_check",
        team_id=team_id,
        total=len(item_ids),
        cached=len(results),
        misses=len(misses),
    )

    if not misses:
        return results

    # Batch misses into chunks and run sentiment workflows concurrently
    client = await async_connect()
    semaphore = asyncio.Semaphore(SENTIMENT_MAX_CONCURRENT)
    chunks = [misses[i : i + SENTIMENT_BATCH_SIZE] for i in range(0, len(misses), SENTIMENT_BATCH_SIZE)]

    async def _run_sentiment_batch(chunk: list[str]) -> dict[str, dict]:
        async with semaphore:
            workflow_id = f"llma-sentiment-cluster-{team_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
            try:
                return await asyncio.wait_for(
                    client.execute_workflow(
                        SENTIMENT_WORKFLOW_NAME,
                        ClassifySentimentInput(
                            team_id=team_id,
                            ids=chunk,
                            analysis_level=analysis_level,
                            date_from=date_from,
                            date_to=date_to,
                        ),
                        id=workflow_id,
                        task_queue=settings.LLMA_SENTIMENT_TASK_QUEUE,
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                        retry_policy=RetryPolicy(maximum_attempts=SENTIMENT_MAX_RETRY_ATTEMPTS),
                        task_timeout=timedelta(seconds=SENTIMENT_WORKFLOW_TIMEOUT),
                    ),
                    timeout=SENTIMENT_PER_BATCH_TIMEOUT,
                )
            except Exception as e:
                logger.warning(
                    "sentiment_batch_failed",
                    team_id=team_id,
                    chunk_size=len(chunk),
                    error=str(e),
                )
                return {}

    try:
        batch_results = await asyncio.wait_for(
            asyncio.gather(*[_run_sentiment_batch(chunk) for chunk in chunks]),
            timeout=SENTIMENT_TOTAL_TIMEOUT,
        )
        for batch in batch_results:
            results.update(batch)
    except TimeoutError:
        logger.warning(
            "sentiment_total_timeout",
            team_id=team_id,
            total_chunks=len(chunks),
            cached_so_far=len(results),
        )

    return results


def _aggregate_sentiment_per_cluster(
    items: list[ClusterItem],
    labels: list[int],
    sentiment_results: dict[str, dict],
) -> dict[int, ClusterSentiment]:
    """Aggregate per-item sentiment into per-cluster sentiment."""
    cluster_items: dict[int, list[str]] = {}
    for i, label in enumerate(labels):
        item_id = _get_item_id(items[i])
        cluster_items.setdefault(label, []).append(item_id)

    result: dict[int, ClusterSentiment] = {}
    for cluster_id, item_ids in cluster_items.items():
        counts: dict[str, int] = {"positive": 0, "neutral": 0, "negative": 0}
        total_score = 0.0
        total_with_sentiment = 0

        for item_id in item_ids:
            s = sentiment_results.get(item_id)
            if not s or "label" not in s:
                continue
            label = s["label"]
            if label in counts:
                counts[label] += 1
            total_score += s.get("score", 0.0)
            total_with_sentiment += 1

        if total_with_sentiment == 0:
            continue

        # Overall label is the majority class
        overall_label = max(counts, key=lambda k: counts[k])
        result[cluster_id] = ClusterSentiment(
            label=overall_label,
            score=total_score / total_with_sentiment,
            counts=counts,
            total=total_with_sentiment,
        )

    return result


def _compute_aggregates(inputs: ComputeAggregatesActivityInputs) -> dict[int, ClusterAggregateMetrics]:
    """Synchronous wrapper that orchestrates metrics + sentiment collection."""
    window_start = parse_datetime(inputs.window_start)
    window_end = parse_datetime(inputs.window_end)
    if window_start is None or window_end is None:
        raise ValueError(f"Invalid datetime: {inputs.window_start}, {inputs.window_end}")

    team = Team.objects.get(id=inputs.team_id)
    all_item_ids = [_get_item_id(item) for item in inputs.items]

    # Phase 1: Fetch operational metrics (cost, latency, tokens, errors)
    t0 = time.monotonic()
    item_metrics = fetch_item_metrics(
        team=team,
        item_ids=all_item_ids,
        window_start=window_start,
        window_end=window_end,
        analysis_level=inputs.analysis_level,
    )
    metrics_ms = (time.monotonic() - t0) * 1000

    cluster_metrics = _aggregate_operational_metrics(inputs.items, inputs.labels, item_metrics)

    # Phase 2: Fetch sentiment (best-effort, async)
    t1 = time.monotonic()
    sentiment_results: dict[str, dict] = {}
    try:
        # Use trace IDs for sentiment (sentiment classifies user messages in generations)
        sentiment_ids = all_item_ids
        sentiment_level = inputs.analysis_level
        sentiment_results = asyncio.run(
            _fetch_sentiment_for_items(
                team_id=inputs.team_id,
                item_ids=sentiment_ids,
                analysis_level=sentiment_level,
                date_from=inputs.window_start,
                date_to=inputs.window_end,
            )
        )
    except Exception as e:
        logger.warning(
            "sentiment_fetch_failed",
            team_id=inputs.team_id,
            error=str(e),
        )
    sentiment_ms = (time.monotonic() - t1) * 1000

    # Merge sentiment into cluster metrics
    if sentiment_results:
        cluster_sentiment = _aggregate_sentiment_per_cluster(inputs.items, inputs.labels, sentiment_results)
        for cluster_id, sentiment in cluster_sentiment.items():
            if cluster_id in cluster_metrics:
                cluster_metrics[cluster_id].sentiment = sentiment

    logger.info(
        "compute_aggregates_completed",
        team_id=inputs.team_id,
        analysis_level=inputs.analysis_level,
        item_count=len(all_item_ids),
        items_with_metrics=len(item_metrics),
        items_with_sentiment=len(sentiment_results),
        clusters=len(cluster_metrics),
        metrics_ms=round(metrics_ms),
        sentiment_ms=round(sentiment_ms),
    )

    return cluster_metrics


@activity.defn
async def compute_cluster_aggregates_activity(
    inputs: ComputeAggregatesActivityInputs,
) -> dict[int, ClusterAggregateMetrics]:
    """Activity 3: Compute aggregate metrics and sentiment for clusters.

    Best-effort: returns whatever it can compute within the time budget.
    If sentiment fails or times out, operational metrics are still returned.
    If the whole activity fails, the workflow continues without metrics.
    """
    async with Heartbeater():
        return await asyncio.to_thread(_compute_aggregates, inputs)
