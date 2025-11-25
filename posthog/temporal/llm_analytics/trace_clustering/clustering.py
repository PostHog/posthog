"""Main clustering orchestration logic.

This module contains the core function that orchestrates the entire clustering pipeline:
1. Fetch trace IDs and embeddings
2. Determine optimal k
3. Perform k-means clustering
4. Generate LLM labels
5. Emit events
"""

import time
import logging

from django.utils.dateparse import parse_datetime

import numpy as np

from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.clustering_utils import (
    calculate_trace_distances,
    determine_optimal_k,
    perform_kmeans_clustering,
    select_representatives_from_distances,
)
from posthog.temporal.llm_analytics.trace_clustering.data import (
    fetch_embeddings_by_trace_ids,
    fetch_trace_ids_for_clustering,
)
from posthog.temporal.llm_analytics.trace_clustering.event_emission import emit_cluster_events
from posthog.temporal.llm_analytics.trace_clustering.labeling import generate_cluster_labels
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusteringInputs,
    ClusteringResult,
    TraceEmbeddings,
    TraceId,
)

logger = logging.getLogger(__name__)


def perform_clustering(inputs: ClusteringInputs) -> ClusteringResult:
    """Perform the complete clustering pipeline.

    This is the main orchestration function that:
    1. Queries and samples trace IDs
    2. Fetches embeddings
    3. Determines optimal k using silhouette score
    4. Performs k-means clustering
    5. Generates LLM-based cluster labels
    6. Emits events to ClickHouse
    7. Returns clustering results

    Args:
        inputs: ClusteringInputs with team_id and parameters

    Returns:
        ClusteringResult with clustering metrics and cluster info
    """
    current_time = parse_datetime(inputs.current_time)
    start_time = current_time

    # Calculate window from lookback_days if not explicitly provided
    if inputs.window_start and inputs.window_end:
        window_start = parse_datetime(inputs.window_start)
        window_end = parse_datetime(inputs.window_end)
    else:
        from datetime import timedelta

        window_end = current_time
        window_start = current_time - timedelta(days=inputs.lookback_days)

    clustering_run_id = f"team_{inputs.team_id}_{window_end.isoformat()}"

    # Fetch trace IDs
    trace_ids: list[TraceId] = fetch_trace_ids_for_clustering(
        team_id=inputs.team_id,
        window_start=window_start,
        window_end=window_end,
        max_samples=inputs.max_samples if inputs.max_samples > 0 else None,
    )

    total_traces = len(trace_ids)

    # Fetch embeddings
    embeddings_map: TraceEmbeddings = fetch_embeddings_by_trace_ids(inputs.team_id, trace_ids, window_start, window_end)
    embeddings_array = np.array(list(embeddings_map.values()))

    # Determine optimal k
    optimal_k, k_scores = determine_optimal_k(embeddings_array, inputs.min_k, inputs.max_k)
    silhouette_score = k_scores.get(optimal_k, 0.0)

    # Perform clustering
    embeddings_ordered = np.array([embeddings_map[tid] for tid in trace_ids if tid in embeddings_map])
    labels, centroids, inertia = perform_kmeans_clustering(embeddings_ordered, optimal_k)

    # Compute distance matrix ONCE for use by representative selection and event emission
    distances_matrix = calculate_trace_distances(embeddings_ordered, centroids)

    # Select representative traces for LLM labeling
    representative_trace_ids = select_representatives_from_distances(
        labels=labels,
        distances_matrix=distances_matrix,
        trace_ids=trace_ids,
        n_closest=constants.DEFAULT_TRACES_PER_CLUSTER_FOR_LABELING,
    )

    # Generate LLM labels
    cluster_labels = generate_cluster_labels(
        team_id=inputs.team_id,
        labels=labels,
        representative_trace_ids=representative_trace_ids,
        optimal_k=optimal_k,
        window_start=window_start,
        window_end=window_end,
    )

    # Emit events
    clusters = emit_cluster_events(
        team_id=inputs.team_id,
        clustering_run_id=clustering_run_id,
        event_timestamp=current_time,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        total_traces=total_traces,
        sampled_traces=total_traces,
        optimal_k=optimal_k,
        silhouette_score=silhouette_score,
        inertia=inertia,
        labels=labels.tolist(),
        centroids=centroids.tolist(),
        trace_ids=trace_ids,
        distances_matrix=distances_matrix,
        cluster_labels=cluster_labels,
    )

    duration = time.time() - start_time.timestamp()

    return ClusteringResult(
        clustering_run_id=clustering_run_id,
        team_id=inputs.team_id,
        timestamp=current_time.isoformat(),
        window_start=window_start,
        window_end=window_end,
        total_traces_analyzed=total_traces,
        sampled_traces_count=total_traces,
        optimal_k=optimal_k,
        silhouette_score=silhouette_score,
        inertia=inertia,
        clusters=clusters,
        duration_seconds=duration,
    )
