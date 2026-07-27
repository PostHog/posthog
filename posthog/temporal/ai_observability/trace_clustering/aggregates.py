"""Compute aggregate metrics (cost, latency, tokens, errors) for clusters.

This activity is best-effort: it returns whatever metrics it managed to compute.
"""

import time
import asyncio

from django.utils.dateparse import parse_datetime

import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai_observability.trace_clustering.data import ItemMetrics, fetch_item_metrics
from posthog.temporal.ai_observability.trace_clustering.models import (
    ClusterAggregateMetrics,
    ClusterItem,
    ComputeAggregatesActivityInputs,
)
from posthog.temporal.common.heartbeat import Heartbeater

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


def _compute_aggregates(inputs: ComputeAggregatesActivityInputs) -> dict[int, ClusterAggregateMetrics]:
    """Synchronous wrapper that orchestrates metrics collection."""
    window_start = parse_datetime(inputs.window_start)
    window_end = parse_datetime(inputs.window_end)
    if window_start is None or window_end is None:
        raise ValueError(f"Invalid datetime: {inputs.window_start}, {inputs.window_end}")

    team = Team.objects.get(id=inputs.team_id)
    all_item_ids = [_get_item_id(item) for item in inputs.items]

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

    logger.info(
        "compute_aggregates_completed",
        team_id=inputs.team_id,
        analysis_level=inputs.analysis_level,
        item_count=len(all_item_ids),
        items_with_metrics=len(item_metrics),
        clusters=len(cluster_metrics),
        metrics_ms=round(metrics_ms),
    )

    return cluster_metrics


@activity.defn
async def compute_cluster_aggregates_activity(
    inputs: ComputeAggregatesActivityInputs,
) -> dict[int, ClusterAggregateMetrics]:
    """Activity 3: Compute aggregate metrics for clusters.

    Best-effort: returns whatever it can compute within the time budget.
    If the whole activity fails, the workflow continues without metrics.
    """
    async with Heartbeater():
        return await asyncio.to_thread(_compute_aggregates, inputs)
