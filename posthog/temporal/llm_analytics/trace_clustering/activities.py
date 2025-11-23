"""Activities for trace clustering workflow."""

import random
import logging
from datetime import datetime
from typing import Optional

import numpy as np
from temporalio import activity

from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.clustering_utils import (
    determine_optimal_k,
    perform_kmeans_clustering,
)
from posthog.temporal.llm_analytics.trace_clustering.models import TraceEmbedding

logger = logging.getLogger(__name__)


@activity.defn
async def query_trace_embeddings_activity(
    team_id: int,
    window_start: str,
    window_end: str,
) -> list[TraceEmbedding]:
    """
    Query trace embeddings from the document_embeddings table.

    Fetches only trace IDs and embedding vectors for clustering.
    Metadata can be fetched later by the UI when displaying clusters.

    Args:
        team_id: Team ID to query embeddings for
        window_start: Start of time window (RFC3339)
        window_end: End of time window (RFC3339)

    Returns:
        List of TraceEmbedding objects with trace_id and embedding
    """
    from django.utils.dateparse import parse_datetime

    from posthog.clickhouse.client.connection import Workload
    from posthog.clickhouse.client.execute import sync_execute

    logger.info(f"Querying trace embeddings for team {team_id} from {window_start} to {window_end}")

    start_dt = parse_datetime(window_start)
    end_dt = parse_datetime(window_end)

    if not start_dt or not end_dt:
        raise ValueError(f"Invalid datetime format: {window_start} or {window_end}")

    # Query only trace_id and embedding - metadata can be fetched by UI later
    query = """
        SELECT
            document_id as trace_id,
            embedding
        FROM document_embeddings
        WHERE team_id = %(team_id)s
            AND timestamp >= %(start_dt)s
            AND timestamp < %(end_dt)s
            AND rendering_type IN (%(minimal_rendering)s, %(detailed_rendering)s)
            AND length(embedding) > 0
        ORDER BY timestamp DESC
    """

    params = {
        "team_id": team_id,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "minimal_rendering": constants.LLMA_TRACE_MINIMAL_RENDERING,
        "detailed_rendering": constants.LLMA_TRACE_DETAILED_RENDERING,
    }

    results = await sync_execute(query, params, workload=Workload.OFFLINE)

    embeddings = []
    for row in results:
        trace_id, embedding = row
        embeddings.append(
            TraceEmbedding(
                trace_id=trace_id,
                embedding=embedding,
            )
        )

    logger.info(f"Found {len(embeddings)} trace embeddings")

    return embeddings


@activity.defn
async def sample_embeddings_activity(
    embeddings: list[TraceEmbedding],
    max_samples: int,
    random_seed: Optional[int] = None,
) -> list[TraceEmbedding]:
    """
    Sample embeddings randomly up to max_samples.

    If there are fewer embeddings than max_samples, returns all embeddings.
    Uses a fixed random seed for reproducibility within a run.

    Args:
        embeddings: List of trace embeddings
        max_samples: Maximum number of embeddings to sample
        random_seed: Random seed for reproducibility (defaults to run ID hash)

    Returns:
        Sampled list of embeddings
    """
    logger.info(f"Sampling up to {max_samples} embeddings from {len(embeddings)} total")

    if len(embeddings) <= max_samples:
        logger.info(f"Using all {len(embeddings)} embeddings (fewer than max_samples)")
        return embeddings

    # Use provided seed or generate from current time
    if random_seed is None:
        random_seed = int(datetime.now().timestamp())

    random.seed(random_seed)
    sampled = random.sample(embeddings, max_samples)

    logger.info(f"Sampled {len(sampled)} embeddings with seed {random_seed}")

    return sampled


@activity.defn
async def determine_optimal_k_activity(
    embeddings: list[TraceEmbedding],
    min_k: int,
    max_k: int,
) -> tuple[int, dict[int, float]]:
    """
    Determine optimal number of clusters using silhouette score.

    Tests k values from min_k to max_k and returns the k with highest
    silhouette score.

    Args:
        embeddings: List of trace embeddings
        min_k: Minimum k to test
        max_k: Maximum k to test

    Returns:
        Tuple of (optimal_k, scores_dict)
    """
    logger.info(f"Determining optimal k from {min_k} to {max_k} for {len(embeddings)} embeddings")

    # Convert to numpy array
    embedding_matrix = np.array([e.embedding for e in embeddings])

    optimal_k, scores = determine_optimal_k(embedding_matrix, min_k, max_k)

    logger.info(f"Optimal k: {optimal_k} (scores: {scores})")

    return optimal_k, scores


@activity.defn
async def perform_clustering_activity(
    embeddings: list[TraceEmbedding],
    k: int,
) -> tuple[list[int], list[list[float]], float]:
    """
    Perform k-means clustering on embeddings.

    Args:
        embeddings: List of trace embeddings
        k: Number of clusters

    Returns:
        Tuple of (labels, centroids, inertia)
        - labels: Cluster assignment for each embedding
        - centroids: Cluster centroids as lists
        - inertia: Sum of squared distances to nearest centroid
    """
    logger.info(f"Performing k-means clustering with k={k} on {len(embeddings)} embeddings")

    # Convert to numpy array
    embedding_matrix = np.array([e.embedding for e in embeddings])

    labels_array, centroids_array, inertia = perform_kmeans_clustering(embedding_matrix, k)

    # Convert to lists for serialization
    labels = labels_array.tolist()
    centroids = centroids_array.tolist()

    logger.info(f"Clustering complete: {k} clusters, inertia={inertia:.2f}")

    return labels, centroids, inertia


@activity.defn
async def emit_cluster_events_activity(
    team_id: int,
    clustering_run_id: str,
    window_start: str,
    window_end: str,
    total_traces: int,
    sampled_traces: int,
    optimal_k: int,
    silhouette_score: float,
    inertia: float,
    labels: list[int],
    embeddings: list[TraceEmbedding],
) -> int:
    """
    Emit $ai_trace_clusters event to ClickHouse.

    Creates a single event containing all clusters with trace IDs.
    The UI can fetch metadata for individual traces as needed.

    Args:
        team_id: Team ID
        clustering_run_id: Unique ID for this clustering run
        window_start: Start of time window
        window_end: End of time window
        total_traces: Total traces analyzed
        sampled_traces: Number of traces sampled
        optimal_k: Number of clusters
        silhouette_score: Clustering quality score
        inertia: K-means inertia
        labels: Cluster assignments
        embeddings: All embeddings (for getting trace IDs per cluster)

    Returns:
        Number of events emitted (always 1)
    """

    logger.info(f"Emitting cluster event for team {team_id}, run {clustering_run_id}")

    # Build clusters array
    clusters = []
    for cluster_id in range(optimal_k):
        # Get all trace IDs in this cluster
        cluster_trace_ids = [embeddings[i].trace_id for i, label in enumerate(labels) if label == cluster_id]

        clusters.append(
            {
                "cluster_id": cluster_id,
                "size": len(cluster_trace_ids),
                "trace_ids": cluster_trace_ids,
            }
        )

    # Build event properties (for future implementation)
    # properties = {
    #     "$ai_clustering_version": constants.CLUSTERING_VERSION,
    #     "$ai_clustering_run_id": clustering_run_id,
    #     "$ai_team_id": team_id,
    #     "$ai_timestamp": datetime.now().isoformat(),
    #     "$ai_window_start": window_start,
    #     "$ai_window_end": window_end,
    #     "$ai_total_traces_analyzed": total_traces,
    #     "$ai_sampled_traces_count": sampled_traces,
    #     "$ai_optimal_k": optimal_k,
    #     "$ai_silhouette_score": silhouette_score,
    #     "$ai_inertia": inertia,
    #     "$ai_clusters": clusters,
    # }

    # TODO: Implement proper event emission once we have the event schema set up
    # For now, just log what we would emit
    logger.info(
        f"Would emit event: {constants.EVENT_NAME} with {optimal_k} clusters, "
        f"{len(clusters)} cluster objects, {sampled_traces} total traces"
    )

    # Placeholder for actual event emission:
    # from posthog.client import sync_execute
    # sync_execute(
    #     "INSERT INTO events ...",
    #     {
    #         "team_id": team_id,
    #         "event": constants.EVENT_NAME,
    #         "properties": properties,
    #         "timestamp": datetime.now(),
    #     }
    # )

    logger.info("Cluster event placeholder completed successfully")

    return 1
