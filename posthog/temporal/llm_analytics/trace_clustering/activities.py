"""Temporal activities for trace clustering workflow.

This module contains the 3 activities that make up the clustering pipeline:
1. perform_clustering_compute_activity - fetch embeddings, cluster, compute distances
2. generate_cluster_labels_activity - LLM labeling for clusters
3. emit_cluster_events_activity - emit results to ClickHouse
"""

import asyncio
from typing import Literal, cast

from django.utils.dateparse import parse_datetime

import numpy as np
import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.clustering import (
    calculate_distances_to_cluster_means,
    calculate_trace_distances,
    compute_2d_coordinates,
    perform_hdbscan_clustering,
    perform_kmeans_with_optimal_k,
    reduce_dimensions_for_clustering,
    reduce_dimensions_pca,
)
from posthog.temporal.llm_analytics.trace_clustering.data import (
    fetch_item_embeddings_for_clustering,
    fetch_item_summaries,
)
from posthog.temporal.llm_analytics.trace_clustering.event_emission import emit_cluster_events
from posthog.temporal.llm_analytics.trace_clustering.labeling import generate_cluster_labels
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusteringActivityInputs,
    ClusteringComputeResult,
    ClusteringMetrics,
    ClusteringResult,
    ClusterItem,
    EmitEventsActivityInputs,
    GenerateLabelsActivityInputs,
    GenerateLabelsActivityOutputs,
    TraceSummary,
)

logger = structlog.get_logger(__name__)


def _perform_clustering_compute(inputs: ClusteringActivityInputs) -> ClusteringComputeResult:
    """CPU-bound compute: fetch embeddings, optionally reduce dimensions, cluster with HDBSCAN.

    Pipeline:
    1. Fetch embeddings from ClickHouse
    2. UMAP dimensionality reduction (3072 -> 15 dims) - skipped if skip_umap_reduction=True
    3. HDBSCAN clustering (auto-determines k, identifies outliers)
    4. Compute distances and select representatives
    5. UMAP to 2D for visualization
    """
    window_start = parse_datetime(inputs.window_start)
    window_end = parse_datetime(inputs.window_end)
    if window_start is None or window_end is None:
        raise ValueError(f"Invalid datetime format: window_start={inputs.window_start}, window_end={inputs.window_end}")

    # Generate run_id with analysis_level for uniqueness and optional label suffix for experiment tracking
    base_run_id = f"{inputs.team_id}_{inputs.analysis_level}_{window_end.strftime('%Y%m%d_%H%M%S')}"
    clustering_run_id = f"{base_run_id}_{inputs.run_label}" if inputs.run_label else base_run_id

    team = Team.objects.get(id=inputs.team_id)

    item_ids, embeddings_map, batch_run_ids_map = fetch_item_embeddings_for_clustering(
        team=team,
        window_start=window_start,
        window_end=window_end,
        max_samples=inputs.max_samples,
        analysis_level=inputs.analysis_level,
        trace_filters=inputs.trace_filters if inputs.trace_filters else None,
    )

    logger.debug(
        "perform_clustering_compute_fetched_embeddings",
        num_items=len(item_ids),
        analysis_level=inputs.analysis_level,
    )

    # Need at least 2 items to perform clustering
    if len(item_ids) < 2:
        logger.warning(
            "Not enough items for clustering",
            item_count=len(item_ids),
            team_id=inputs.team_id,
            analysis_level=inputs.analysis_level,
        )
        return ClusteringComputeResult(
            clustering_run_id=clustering_run_id,
            items=[],
            labels=[],
            centroids=[],
            distances=[],
            coords_2d=[],
            centroid_coords_2d=[],
            probabilities=[],
            analysis_level=inputs.analysis_level,
            num_noise_points=0,
            batch_run_ids={},
        )

    # Fetch summaries to get parent trace_id for generation-level clustering
    summaries = fetch_item_summaries(
        team=team,
        item_ids=item_ids,
        batch_run_ids=batch_run_ids_map,
        window_start=window_start,
        window_end=window_end,
        analysis_level=inputs.analysis_level,
    )

    # Build ClusterItem list with explicit trace_id and generation_id
    # For generation-level, skip items without trace_id in summary to avoid invalid data
    items: list[ClusterItem] = []
    filtered_embeddings: list[list[float]] = []
    skipped_missing_trace_id = 0

    for item_id in item_ids:
        summary: TraceSummary | dict[str, str] = summaries.get(item_id, {})
        if inputs.analysis_level == "generation":
            # For generation-level: item_id is generation_id, trace_id comes from summary
            trace_id = summary.get("trace_id")
            if not trace_id:
                skipped_missing_trace_id += 1
                continue
            items.append(ClusterItem(trace_id=trace_id, generation_id=item_id))
        else:
            # For trace-level: item_id is trace_id, no generation_id
            items.append(ClusterItem(trace_id=item_id, generation_id=None))
        filtered_embeddings.append(embeddings_map[item_id])

    if skipped_missing_trace_id > 0:
        logger.warning(
            "Skipped generations missing trace_id",
            skipped_count=skipped_missing_trace_id,
            team_id=inputs.team_id,
        )

    embeddings_array = np.array(filtered_embeddings)

    # Step 0: Optionally L2 normalize embeddings
    if inputs.embedding_normalization == "l2":
        # L2 normalize each embedding vector (row-wise normalization)
        norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
        # Avoid division by zero for zero vectors
        norms = np.where(norms == 0, 1, norms)
        embeddings_array = embeddings_array / norms

    # Step 1: Optionally reduce dimensions for clustering
    if inputs.dimensionality_reduction_method == "none":
        # Run HDBSCAN directly on raw embeddings (3072 dims or normalized)
        clustering_embeddings = embeddings_array
    elif inputs.dimensionality_reduction_method == "pca":
        clustering_embeddings, _ = reduce_dimensions_pca(
            embeddings_array,
            n_components=inputs.dimensionality_reduction_ndims,
        )
    else:
        # Default to UMAP
        clustering_embeddings, _ = reduce_dimensions_for_clustering(
            embeddings_array,
            n_components=inputs.dimensionality_reduction_ndims,
            n_neighbors=constants.DEFAULT_UMAP_N_NEIGHBORS,
            min_dist=constants.DEFAULT_UMAP_MIN_DIST,
        )

    # Step 2: Perform clustering based on method
    clustering_params = inputs.clustering_method_params or {}

    if inputs.clustering_method == "kmeans":
        # K-means with optimal k selection via silhouette score
        min_k = clustering_params.get("min_k", inputs.min_k)
        max_k = clustering_params.get("max_k", inputs.max_k)
        kmeans_result = perform_kmeans_with_optimal_k(
            clustering_embeddings,
            min_k=min_k,
            max_k=max_k,
        )
        labels_array = np.array(kmeans_result.labels)
        centroids_array = np.array(kmeans_result.centroids)
        # K-means doesn't have probabilities or noise
        probabilities = [1.0] * len(labels_array)
        num_noise_points = 0
        labels_list = kmeans_result.labels
        centroids_list = kmeans_result.centroids

        # Step 3: Compute distance matrix
        distances_matrix = calculate_trace_distances(clustering_embeddings, centroids_array)
    else:
        # Default to HDBSCAN
        min_cluster_size_fraction = clustering_params.get(
            "min_cluster_size_fraction", constants.DEFAULT_MIN_CLUSTER_SIZE_FRACTION
        )
        min_samples = clustering_params.get("min_samples", constants.DEFAULT_HDBSCAN_MIN_SAMPLES)
        hdbscan_result = perform_hdbscan_clustering(
            clustering_embeddings,
            min_cluster_size_fraction=min_cluster_size_fraction,
            min_samples=min_samples,
        )
        labels_array = np.array(hdbscan_result.labels)
        centroids_array = (
            np.array(hdbscan_result.centroids)
            if hdbscan_result.centroids
            else np.zeros((0, clustering_embeddings.shape[1]))
        )
        probabilities = hdbscan_result.probabilities
        num_noise_points = hdbscan_result.num_noise_points
        labels_list = hdbscan_result.labels
        centroids_list = hdbscan_result.centroids

        # Step 3: Compute distance matrix (in clustering space)
        distances_matrix = calculate_distances_to_cluster_means(
            clustering_embeddings,
            labels_array,
            centroids_array,
        )

    # Step 4: Compute 2D coordinates for visualization
    # Use the same embeddings that went into clustering so the scatter plot accurately represents the clustering space
    coords_2d, centroid_coords_2d = compute_2d_coordinates(
        clustering_embeddings,
        centroids_array,
        method=cast(Literal["umap", "pca", "tsne"], inputs.visualization_method),
    )

    return ClusteringComputeResult(
        clustering_run_id=clustering_run_id,
        items=items,
        labels=labels_list,
        centroids=centroids_list,
        distances=distances_matrix.tolist(),
        coords_2d=coords_2d.tolist(),
        centroid_coords_2d=centroid_coords_2d.tolist(),
        probabilities=probabilities,
        analysis_level=inputs.analysis_level,
        num_noise_points=num_noise_points,
        batch_run_ids=batch_run_ids_map,
    )


@activity.defn
async def perform_clustering_compute_activity(inputs: ClusteringActivityInputs) -> ClusteringComputeResult:
    """Activity 1: CPU-bound compute - fetch embeddings, cluster, compute distances.

    This activity handles all the compute-intensive work:
    - Fetches embeddings from ClickHouse
    - Performs clustering (HDBSCAN or k-means)
    - Calculates distances from each trace to all centroids
    - Computes 2D coordinates for visualization

    Output is ~150 KB (labels, centroids, distances, coords).
    Embeddings (~3-4 MB) are not passed to subsequent activities.
    """
    return await asyncio.to_thread(_perform_clustering_compute, inputs)


def _generate_cluster_labels(inputs: GenerateLabelsActivityInputs) -> GenerateLabelsActivityOutputs:
    """LLM labeling implementation called by the activity.

    Uses a LangGraph agent that can iteratively explore cluster structure
    and generate high-quality, distinctive labels.
    """
    window_start = parse_datetime(inputs.window_start)
    window_end = parse_datetime(inputs.window_end)
    if window_start is None or window_end is None:
        raise ValueError(f"Invalid datetime format: window_start={inputs.window_start}, window_end={inputs.window_end}")

    team = Team.objects.get(id=inputs.team_id)

    cluster_labels = generate_cluster_labels(
        team=team,
        items=inputs.items,
        labels=inputs.labels,
        item_metadata=inputs.item_metadata,
        centroid_coords_2d=inputs.centroid_coords_2d,
        window_start=window_start,
        window_end=window_end,
        batch_run_ids=inputs.batch_run_ids,
        analysis_level=inputs.analysis_level,
    )

    return GenerateLabelsActivityOutputs(cluster_labels=cluster_labels)


@activity.defn
async def generate_cluster_labels_activity(inputs: GenerateLabelsActivityInputs) -> GenerateLabelsActivityOutputs:
    """Activity 2: LLM labeling - generate titles and descriptions for clusters.

    This activity runs a LangGraph agent (Claude Sonnet 4.5) that iteratively
    explores cluster structure using tools to sample traces and generate
    high-quality, distinctive labels.

    Timeout: 10 minutes for full agent run
    Input: ~250 KB (trace IDs, cluster data, coordinates)
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
        items=inputs.items,
        distances_matrix=np.array(inputs.distances),
        cluster_labels=inputs.cluster_labels,
        coords_2d=np.array(inputs.coords_2d),
        centroid_coords_2d=np.array(inputs.centroid_coords_2d),
        batch_run_ids=inputs.batch_run_ids,
        clustering_params=inputs.clustering_params,
        analysis_level=inputs.analysis_level,
    )

    return ClusteringResult(
        clustering_run_id=inputs.clustering_run_id,
        team_id=inputs.team_id,
        timestamp=inputs.window_end,
        window_start=inputs.window_start,
        window_end=inputs.window_end,
        metrics=ClusteringMetrics(
            total_items_analyzed=len(inputs.items),
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
