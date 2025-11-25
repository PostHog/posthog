"""Main clustering orchestration logic.

This module contains the core function that orchestrates the entire clustering pipeline:
1. Fetch trace IDs and embeddings
2. Perform k-means clustering with optimal k selection
3. Select representative traces for labeling
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
    perform_kmeans_with_optimal_k,
    select_representatives_from_distances,
)
from posthog.temporal.llm_analytics.trace_clustering.data import fetch_trace_embeddings_for_clustering
from posthog.temporal.llm_analytics.trace_clustering.event_emission import emit_cluster_events
from posthog.temporal.llm_analytics.trace_clustering.labeling import generate_cluster_labels
from posthog.temporal.llm_analytics.trace_clustering.models import ClusteringInputs, ClusteringMetrics, ClusteringResult

logger = logging.getLogger(__name__)


def perform_clustering(inputs: ClusteringInputs) -> ClusteringResult:
    """Perform the complete clustering pipeline.

    This is the main orchestration function that:
    1. Fetches trace IDs and embeddings from ClickHouse
    2. Performs k-means clustering with optimal k selection
    3. Computes distances and selects representative traces
    4. Generates LLM-based cluster labels
    5. Emits events to ClickHouse

    Args:
        inputs: ClusteringInputs with team_id and parameters

    Returns:
        ClusteringResult with clustering metrics and cluster info
    """
    start_time = parse_datetime(inputs.current_time)
    metrics = ClusteringMetrics()

    # Calculate window from lookback_days if not explicitly provided
    if inputs.window_start and inputs.window_end:
        window_start = parse_datetime(inputs.window_start)
        window_end = parse_datetime(inputs.window_end)
    else:
        from datetime import timedelta

        window_end = start_time
        window_start = start_time - timedelta(days=inputs.lookback_days)

    clustering_run_id = f"team_{inputs.team_id}_{window_end.isoformat()}"

    # Fetch trace IDs and embeddings
    trace_ids, embeddings_map = fetch_trace_embeddings_for_clustering(
        team_id=inputs.team_id,
        window_start=window_start,
        window_end=window_end,
        max_samples=inputs.max_samples,
    )

    metrics.total_traces_analyzed = len(trace_ids)
    embeddings_array = np.array(list(embeddings_map.values()))

    # Perform clustering with optimal k selection
    kmeans_result = perform_kmeans_with_optimal_k(embeddings_array, inputs.min_k, inputs.max_k)

    # Compute distance matrix for use by representative selection and event emission
    distances_matrix = calculate_trace_distances(embeddings_array, np.array(kmeans_result.centroids))

    # Select representative traces for LLM labeling
    representative_trace_ids = select_representatives_from_distances(
        labels=np.array(kmeans_result.labels),
        distances_matrix=distances_matrix,
        trace_ids=trace_ids,
        n_closest=constants.DEFAULT_TRACES_PER_CLUSTER_FOR_LABELING,
    )

    # Generate LLM labels
    cluster_labels = generate_cluster_labels(
        team_id=inputs.team_id,
        labels=np.array(kmeans_result.labels),
        representative_trace_ids=representative_trace_ids,
        window_start=window_start,
        window_end=window_end,
    )

    # Emit events
    clusters = emit_cluster_events(
        team_id=inputs.team_id,
        clustering_run_id=clustering_run_id,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        labels=kmeans_result.labels,
        centroids=kmeans_result.centroids,
        trace_ids=trace_ids,
        distances_matrix=distances_matrix,
        cluster_labels=cluster_labels,
    )

    metrics.num_clusters = len(kmeans_result.centroids)
    metrics.duration_seconds = time.time() - start_time.timestamp()

    return ClusteringResult(
        clustering_run_id=clustering_run_id,
        team_id=inputs.team_id,
        timestamp=start_time.isoformat(),
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        metrics=metrics,
        clusters=clusters,
    )
