"""Temporal activities for the MCP analytics intent-clustering pipeline.

The pipeline is intentionally simpler than LLM analytics trace clustering:
- One activity to emit embedding requests for new intents + span snippets.
- One activity to cluster intents and emit the result event.

Compared with `posthog/temporal/llm_analytics/trace_clustering/`, we skip the
separate labeling activity (we call the LLM inline per-cluster, which is fine
because intent strings are short) and skip the aggregate-metrics activity (we
fold those into the compute step since we already have the data joined).
"""

import asyncio
from datetime import datetime

import numpy as np
import structlog
from django.utils.dateparse import parse_datetime
from temporalio import activity

from posthog.api.embedding_worker import emit_embedding_request
from posthog.models.team import Team
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.llm_analytics.trace_clustering.clustering import (
    perform_hdbscan_clustering,
    reduce_dimensions_for_clustering,
)
from posthog.temporal.mcp_analytics.constants import (
    AI_SPAN_REASONING_DOCUMENT_TYPE,
    DEFAULT_HDBSCAN_MIN_SAMPLES,
    DEFAULT_MIN_CLUSTER_SIZE_FRACTION,
    DEFAULT_UMAP_N_COMPONENTS,
    EMBEDDING_RENDERING,
    INTENT_DOCUMENT_TYPE,
    MCP_ANALYTICS_PRODUCT,
    MIN_INTENTS_FOR_CLUSTERING,
    NOISE_CLUSTER_ID,
)
from posthog.temporal.mcp_analytics.data import (
    fetch_already_embedded_document_ids,
    fetch_intent_embeddings,
    fetch_intent_stats,
    fetch_span_reasoning_snippets,
)
from posthog.temporal.mcp_analytics.event_emission import emit_intent_clusters_event
from posthog.temporal.mcp_analytics.labeling import label_cluster
from posthog.temporal.mcp_analytics.models import (
    EmbeddingEmitActivityInputs,
    EmbeddingEmitResult,
    IntentCluster,
    IntentClusterMember,
    IntentClusteringActivityInputs,
    IntentClusteringResult,
    IntentStat,
)

logger = structlog.get_logger(__name__)


def _parse_window(window_start: str, window_end: str) -> tuple[datetime, datetime]:
    start = parse_datetime(window_start)
    end = parse_datetime(window_end)
    if start is None or end is None:
        raise ValueError(f"Invalid datetime: start={window_start} end={window_end}")
    return start, end


def _emit_mcp_embedding_requests(inputs: EmbeddingEmitActivityInputs) -> EmbeddingEmitResult:
    window_start, window_end = _parse_window(inputs.window_start, inputs.window_end)
    team = Team.objects.get(id=inputs.team_id)

    intent_stats = fetch_intent_stats(
        team=team,
        window_start=window_start,
        window_end=window_end,
        max_samples=inputs.max_intent_samples,
    )
    already_intent = fetch_already_embedded_document_ids(
        team=team,
        document_type=INTENT_DOCUMENT_TYPE,
        embedding_model=inputs.embedding_model,
    )
    intents_emitted = 0
    for stat in intent_stats:
        if stat.intent in already_intent:
            continue
        emit_embedding_request(
            content=stat.intent,
            team_id=inputs.team_id,
            product=MCP_ANALYTICS_PRODUCT,
            document_type=INTENT_DOCUMENT_TYPE,
            rendering=EMBEDDING_RENDERING,
            document_id=stat.intent,
            models=[inputs.embedding_model],
            metadata={
                "total_calls": stat.total_calls,
                "error_count": stat.error_count,
                "empty_response_count": stat.empty_response_count,
                "distinct_tools_attempted": stat.distinct_tools_attempted,
                "dominant_tool": stat.dominant_tool,
            },
        )
        intents_emitted += 1

    span_snippets = fetch_span_reasoning_snippets(
        team=team,
        window_start=window_start,
        window_end=window_end,
        max_samples=inputs.max_span_samples,
    )
    already_span = fetch_already_embedded_document_ids(
        team=team,
        document_type=AI_SPAN_REASONING_DOCUMENT_TYPE,
        embedding_model=inputs.embedding_model,
    )
    spans_emitted = 0
    for document_id, content in span_snippets:
        if document_id in already_span:
            continue
        emit_embedding_request(
            content=content,
            team_id=inputs.team_id,
            product=MCP_ANALYTICS_PRODUCT,
            document_type=AI_SPAN_REASONING_DOCUMENT_TYPE,
            rendering=EMBEDDING_RENDERING,
            document_id=document_id,
            models=[inputs.embedding_model],
        )
        spans_emitted += 1

    logger.info(
        "mcp_analytics_embedding_emit_done",
        team_id=inputs.team_id,
        intents_emitted=intents_emitted,
        spans_emitted=spans_emitted,
    )
    return EmbeddingEmitResult(intents_emitted=intents_emitted, spans_emitted=spans_emitted)


@activity.defn
async def emit_mcp_embedding_requests_activity(
    inputs: EmbeddingEmitActivityInputs,
) -> EmbeddingEmitResult:
    """Emit Kafka embedding requests for any intents / span snippets not yet embedded.

    Dedup is done by comparing against `document_embeddings` for the team + model
    combo. The Rust embedding worker handles the OpenAI call and ClickHouse writes
    asynchronously.
    """
    async with Heartbeater():
        return await asyncio.to_thread(_emit_mcp_embedding_requests, inputs)


def _cluster_intents(inputs: IntentClusteringActivityInputs) -> IntentClusteringResult:
    window_start, window_end = _parse_window(inputs.window_start, inputs.window_end)
    team = Team.objects.get(id=inputs.team_id)
    clustering_run_id = f"mcp_{inputs.team_id}_{window_end.strftime('%Y%m%d_%H%M%S')}"

    intent_stats = fetch_intent_stats(
        team=team,
        window_start=window_start,
        window_end=window_end,
        max_samples=inputs.max_samples,
    )

    if len(intent_stats) < MIN_INTENTS_FOR_CLUSTERING:
        logger.warning(
            "mcp_analytics_not_enough_intents",
            team_id=inputs.team_id,
            num_intents=len(intent_stats),
        )
        result = IntentClusteringResult(
            clustering_run_id=clustering_run_id,
            team_id=inputs.team_id,
            window_start=inputs.window_start,
            window_end=inputs.window_end,
            num_intents_analyzed=len(intent_stats),
            clusters=[],
        )
        emit_intent_clusters_event(inputs.team_id, result)
        return result

    embeddings_map = fetch_intent_embeddings(
        team=team,
        intents=[s.intent for s in intent_stats],
        embedding_model=inputs.embedding_model,
    )

    # Drop intents whose embedding hasn't landed yet — they'll cluster next run.
    aligned_stats: list[IntentStat] = []
    aligned_embeddings: list[list[float]] = []
    for stat in intent_stats:
        emb = embeddings_map.get(stat.intent)
        if emb:
            aligned_stats.append(stat)
            aligned_embeddings.append(emb)

    if len(aligned_stats) < MIN_INTENTS_FOR_CLUSTERING:
        logger.warning(
            "mcp_analytics_not_enough_aligned_embeddings",
            team_id=inputs.team_id,
            embedded_count=len(aligned_stats),
            stat_count=len(intent_stats),
        )
        result = IntentClusteringResult(
            clustering_run_id=clustering_run_id,
            team_id=inputs.team_id,
            window_start=inputs.window_start,
            window_end=inputs.window_end,
            num_intents_analyzed=len(aligned_stats),
            clusters=[],
        )
        emit_intent_clusters_event(inputs.team_id, result)
        return result

    embedding_array = np.array(aligned_embeddings, dtype=np.float32)

    reduced, _ = reduce_dimensions_for_clustering(
        embedding_array,
        n_components=DEFAULT_UMAP_N_COMPONENTS,
    )
    hdbscan_result = perform_hdbscan_clustering(
        reduced,
        min_cluster_size_fraction=DEFAULT_MIN_CLUSTER_SIZE_FRACTION,
        min_samples=DEFAULT_HDBSCAN_MIN_SAMPLES,
    )

    clusters = _build_intent_clusters(
        aligned_stats=aligned_stats,
        labels=hdbscan_result.labels,
        centroids=hdbscan_result.centroids,
        embeddings=embedding_array,
    )

    result = IntentClusteringResult(
        clustering_run_id=clustering_run_id,
        team_id=inputs.team_id,
        window_start=inputs.window_start,
        window_end=inputs.window_end,
        num_intents_analyzed=len(aligned_stats),
        clusters=clusters,
    )
    emit_intent_clusters_event(inputs.team_id, result)
    return result


@activity.defn
async def cluster_intents_activity(inputs: IntentClusteringActivityInputs) -> IntentClusteringResult:
    """Fetch intents, look up embeddings, cluster with HDBSCAN, label clusters, emit event."""
    async with Heartbeater():
        return await asyncio.to_thread(_cluster_intents, inputs)


def _build_intent_clusters(
    aligned_stats: list[IntentStat],
    labels: list[int],
    centroids: list[list[float]],
    embeddings: np.ndarray,
) -> list[IntentCluster]:
    """Group items by HDBSCAN label, label each cluster via LLM, attach aggregate signal.

    Noise cluster (-1) is intentionally excluded — by definition those items don't
    form a coherent intent group and shouldn't surface as a "missing tool" candidate.
    """
    non_noise_ids = sorted({int(c) for c in labels if c != NOISE_CLUSTER_ID})

    clusters: list[IntentCluster] = []
    for cluster_id in non_noise_ids:
        member_indices = [int(i) for i, lab in enumerate(labels) if lab == cluster_id]
        if not member_indices:
            continue

        member_stats = [aligned_stats[i] for i in member_indices]
        centroid_vec = centroids[cluster_id] if cluster_id < len(centroids) else []
        if centroid_vec:
            centroid_arr = np.array(centroid_vec, dtype=np.float32)
            distances = np.linalg.norm(embeddings[member_indices] - centroid_arr, axis=1)
        else:
            distances = np.zeros(len(member_indices))

        order = np.argsort(distances)
        members = [
            IntentClusterMember(
                intent=member_stats[idx].intent,
                stat=member_stats[idx],
                distance_to_centroid=float(distances[idx]),
            )
            for idx in order
        ]

        # Label using up to 15 closest intents to the centroid (most representative).
        label = label_cluster([m.stat for m in members[:15]])
        total_calls = sum(s.total_calls for s in member_stats)
        total_errors = sum(s.error_count for s in member_stats)
        total_empty = sum(s.empty_response_count for s in member_stats)
        avg_distinct = sum(s.distinct_tools_attempted for s in member_stats) / len(member_stats)

        clusters.append(
            IntentCluster(
                cluster_id=cluster_id,
                size=len(members),
                title=label.title,
                description=label.description,
                gap_score=label.gap_score,
                centroid=list(centroid_vec),
                members=members,
                aggregate_error_rate=(total_errors / total_calls) if total_calls else 0.0,
                aggregate_empty_rate=(total_empty / total_calls) if total_calls else 0.0,
                avg_distinct_tools_attempted=avg_distinct,
            )
        )

    clusters.sort(key=lambda c: c.gap_score, reverse=True)
    return clusters


__all__ = [
    "emit_mcp_embedding_requests_activity",
    "cluster_intents_activity",
]
