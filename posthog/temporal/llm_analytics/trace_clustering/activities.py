"""Temporal activities for trace clustering workflow.

This module contains the 3 activities that make up the clustering pipeline:
1. perform_clustering_compute_activity - fetch embeddings, cluster, compute distances
2. generate_cluster_labels_activity - LLM labeling for clusters
3. emit_cluster_events_activity - emit results to ClickHouse
"""

import asyncio

from django.utils.dateparse import parse_datetime

import numpy as np
import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.clustering import (
    calculate_distances_to_cluster_means,
    compute_2d_coordinates,
    perform_hdbscan_clustering,
    reduce_dimensions_for_clustering,
    select_representatives_by_probability,
)
from posthog.temporal.llm_analytics.trace_clustering.data import fetch_trace_embeddings_for_clustering
from posthog.temporal.llm_analytics.trace_clustering.event_emission import emit_cluster_events
from posthog.temporal.llm_analytics.trace_clustering.labeling import generate_cluster_labels
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusteringActivityInputs,
    ClusteringComputeResult,
    ClusteringMetrics,
    ClusteringResult,
    EmitEventsActivityInputs,
    GenerateLabelsActivityInputs,
    GenerateLabelsActivityOutputs,
)

logger = structlog.get_logger(__name__)


def _perform_clustering_compute(inputs: ClusteringActivityInputs) -> ClusteringComputeResult:
    """CPU-bound compute: fetch embeddings, reduce dimensions, cluster with HDBSCAN.

    Pipeline:
    1. Fetch embeddings from ClickHouse
    2. UMAP dimensionality reduction (3072 -> 15 dims)
    3. HDBSCAN clustering (auto-determines k, identifies outliers)
    4. Compute distances and select representatives
    5. UMAP to 2D for visualization
    """
    window_start = parse_datetime(inputs.window_start)
    window_end = parse_datetime(inputs.window_end)
    if window_start is None or window_end is None:
        raise ValueError(f"Invalid datetime format: window_start={inputs.window_start}, window_end={inputs.window_end}")

    clustering_run_id = f"{inputs.team_id}_{window_end.strftime('%Y%m%d_%H%M%S')}"

    team = Team.objects.get(id=inputs.team_id)

    trace_ids, embeddings_map = fetch_trace_embeddings_for_clustering(
        team=team,
        window_start=window_start,
        window_end=window_end,
        max_samples=inputs.max_samples,
    )

    embeddings_array = np.array(list(embeddings_map.values()))

    # Step 1: Reduce dimensions for clustering (3072 -> 15 dims)
    reduced_embeddings, _ = reduce_dimensions_for_clustering(
        embeddings_array,
        n_components=constants.DEFAULT_UMAP_N_COMPONENTS,
        n_neighbors=constants.DEFAULT_UMAP_N_NEIGHBORS,
        min_dist=constants.DEFAULT_UMAP_MIN_DIST,
    )

    # Step 2: HDBSCAN clustering on reduced embeddings
    hdbscan_result = perform_hdbscan_clustering(
        reduced_embeddings,
        min_cluster_size_fraction=constants.DEFAULT_MIN_CLUSTER_SIZE_FRACTION,
        min_samples=constants.DEFAULT_HDBSCAN_MIN_SAMPLES,
    )

    labels_array = np.array(hdbscan_result.labels)
    centroids_array = (
        np.array(hdbscan_result.centroids) if hdbscan_result.centroids else np.zeros((0, reduced_embeddings.shape[1]))
    )

    # Step 3: Compute distance matrix (in reduced space)
    distances_matrix = calculate_distances_to_cluster_means(
        reduced_embeddings,
        labels_array,
        centroids_array,
    )

    # Step 4: Select representatives using HDBSCAN probabilities
    representative_trace_ids = select_representatives_by_probability(
        labels=labels_array,
        probabilities=np.array(hdbscan_result.probabilities),
        trace_ids=trace_ids,
        n_representatives=constants.DEFAULT_TRACES_PER_CLUSTER_FOR_LABELING,
    )

    # Step 5: Compute 2D coordinates for visualization (use original embeddings for better spread)
    # We need centroids in original embedding space for transform - compute as cluster means
    original_centroids = []
    for cluster_id in sorted(set(hdbscan_result.labels) - {constants.NOISE_CLUSTER_ID}):
        cluster_mask = labels_array == cluster_id
        cluster_center = embeddings_array[cluster_mask].mean(axis=0)
        original_centroids.append(cluster_center)
    original_centroids_array = (
        np.array(original_centroids) if original_centroids else np.zeros((0, embeddings_array.shape[1]))
    )

    coords_2d, centroid_coords_2d = compute_2d_coordinates(
        embeddings_array,  # Use original 3072-dim embeddings for visualization
        original_centroids_array,
    )

    return ClusteringComputeResult(
        clustering_run_id=clustering_run_id,
        trace_ids=trace_ids,
        labels=hdbscan_result.labels,
        centroids=hdbscan_result.centroids,
        distances=distances_matrix.tolist(),
        representative_trace_ids=representative_trace_ids,
        coords_2d=coords_2d.tolist(),
        centroid_coords_2d=centroid_coords_2d.tolist(),
        probabilities=hdbscan_result.probabilities,
        num_noise_points=hdbscan_result.num_noise_points,
    )


@activity.defn
async def perform_clustering_compute_activity(inputs: ClusteringActivityInputs) -> ClusteringComputeResult:
    """Activity 1: CPU-bound compute - fetch embeddings, cluster, compute distances.

    This activity handles all the compute-intensive work:
    - Fetches embeddings from ClickHouse
    - Performs k-means clustering with optimal k selection
    - Calculates distances from each trace to all centroids
    - Selects representative traces for labeling

    Output is ~150 KB (labels, centroids, distances, representative_trace_ids).
    Embeddings (~3-4 MB) are not passed to subsequent activities.
    """
    return await asyncio.to_thread(_perform_clustering_compute, inputs)


def _generate_cluster_labels(inputs: GenerateLabelsActivityInputs) -> GenerateLabelsActivityOutputs:
    """LLM labeling implementation called by the activity."""
    window_start = parse_datetime(inputs.window_start)
    window_end = parse_datetime(inputs.window_end)
    if window_start is None or window_end is None:
        raise ValueError(f"Invalid datetime format: window_start={inputs.window_start}, window_end={inputs.window_end}")

    # Fetch team object for HogQL queries
    team = Team.objects.get(id=inputs.team_id)

    cluster_labels = generate_cluster_labels(
        team=team,
        labels=np.array(inputs.labels),
        representative_trace_ids=inputs.representative_trace_ids,
        window_start=window_start,
        window_end=window_end,
    )

    return GenerateLabelsActivityOutputs(cluster_labels=cluster_labels)


@activity.defn
async def generate_cluster_labels_activity(inputs: GenerateLabelsActivityInputs) -> GenerateLabelsActivityOutputs:
    """Activity 2: LLM labeling - generate titles and descriptions for clusters.

    This activity has a longer timeout (240s) for the LLM API call.
    It fetches trace summaries internally and calls OpenAI to generate labels.

    Input: ~2.5 KB (representative trace IDs)
    Output: ~4 KB (cluster labels)
    """
    return await asyncio.to_thread(_generate_cluster_labels, inputs)


def _emit_cluster_events(inputs: EmitEventsActivityInputs) -> ClusteringResult:
    """Event emission implementation called by the activity."""
    clusters = emit_cluster_events(
        team_id=inputs.team_id,
        clustering_run_id=inputs.clustering_run_id,
        window_start=inputs.window_start,
        window_end=inputs.window_end,
        labels=inputs.labels,
        centroids=inputs.centroids,
        trace_ids=inputs.trace_ids,
        distances_matrix=np.array(inputs.distances),
        cluster_labels=inputs.cluster_labels,
        coords_2d=np.array(inputs.coords_2d),
        centroid_coords_2d=np.array(inputs.centroid_coords_2d),
    )

    return ClusteringResult(
        clustering_run_id=inputs.clustering_run_id,
        team_id=inputs.team_id,
        timestamp=inputs.window_end,
        window_start=inputs.window_start,
        window_end=inputs.window_end,
        metrics=ClusteringMetrics(
            total_traces_analyzed=len(inputs.trace_ids),
            num_clusters=len(inputs.centroids),
        ),
        clusters=clusters,
    )


@activity.defn
async def emit_cluster_events_activity(inputs: EmitEventsActivityInputs) -> ClusteringResult:
    """Activity 3: Emit clustering results to ClickHouse.

    This activity builds the cluster data structures and emits the
    $ai_trace_clusters event containing all clustering metadata.

    Input: ~150 KB (all clustering data)
    Output: ClusteringResult with metrics and cluster info
    """
    return await asyncio.to_thread(_emit_cluster_events, inputs)
