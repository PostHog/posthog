"""Event emission for clustering results.

This module contains functions for emitting clustering results to ClickHouse:
- Build cluster data structures with centroids and distances
- Emit $ai_trace_clusters event with all clustering metadata
"""

import uuid
import logging
import dataclasses
from datetime import datetime

import numpy as np

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.temporal.llm_analytics.trace_clustering import constants
from posthog.temporal.llm_analytics.trace_clustering.models import ClusterData, ClusterLabel, TraceId

logger = logging.getLogger(__name__)


def emit_cluster_events(
    team_id: int,
    clustering_run_id: str,
    event_timestamp: datetime,
    window_start: str,
    window_end: str,
    total_traces: int,
    sampled_traces: int,
    optimal_k: int,
    silhouette_score: float,
    inertia: float,
    labels: list[int],
    centroids: list[list[float]],
    trace_ids: list[TraceId],
    distances_matrix: np.ndarray,
    cluster_labels: dict[int, ClusterLabel],
) -> list[ClusterData]:
    """Emit $ai_trace_clusters event to ClickHouse.

    Creates a single event containing all clusters with trace IDs, centroids, and LLM-generated labels.
    The UI can fetch metadata for individual traces as needed.

    Args:
        team_id: Team ID
        clustering_run_id: Unique ID for this clustering run
        event_timestamp: Timestamp for the event (from workflow.now())
        window_start: Start of time window
        window_end: End of time window
        total_traces: Total traces analyzed
        sampled_traces: Number of traces sampled
        optimal_k: Number of clusters
        silhouette_score: Clustering quality score
        inertia: K-means inertia
        labels: Cluster assignments
        centroids: Cluster centroids (center points in embedding space)
        trace_ids: All trace IDs being clustered
        distances_matrix: Pre-computed distances from each trace to all centroids
        cluster_labels: Dict mapping cluster_id -> ClusterLabel

    Returns:
        List of ClusterData objects emitted
    """
    team = Team.objects.get(id=team_id)

    # Build clusters array with centroids and trace distances
    clusters = _build_cluster_data(
        optimal_k=optimal_k,
        labels=labels,
        trace_ids=trace_ids,
        distances_matrix=distances_matrix,
        centroids=centroids,
        cluster_labels=cluster_labels,
    )

    # Build and emit event
    event_uuid = uuid.uuid4()

    properties = {
        "$ai_clustering_run_id": clustering_run_id,
        "$ai_window_start": window_start,
        "$ai_window_end": window_end,
        "$ai_total_traces_analyzed": total_traces,
        "$ai_sampled_traces_count": sampled_traces,
        "$ai_clusters": [dataclasses.asdict(c) for c in clusters],
    }

    create_event(
        event_uuid=event_uuid,
        event=constants.EVENT_NAME,
        team=team,
        distinct_id=f"trace_clustering_{team_id}",
        timestamp=event_timestamp,
        properties=properties,
        person_id=None,
    )

    return clusters


def _build_cluster_data(
    optimal_k: int,
    labels: list[int],
    trace_ids: list[str],
    distances_matrix: np.ndarray,
    centroids: list[list[float]],
    cluster_labels: dict[int, ClusterLabel],
) -> list[ClusterData]:
    """Build cluster data structure with traces and metadata.

    Args:
        optimal_k: Number of clusters
        labels: Cluster assignments for each trace
        trace_ids: All trace IDs
        distances_matrix: Distance matrix (num_traces x num_clusters)
        centroids: Cluster centroids
        cluster_labels: Dict mapping cluster_id -> ClusterLabel

    Returns:
        List of ClusterData objects
    """
    clusters = []

    for cluster_id in range(optimal_k):
        # Get all trace IDs in this cluster with their distances
        cluster_trace_data = []
        for i, label in enumerate(labels):
            if label == cluster_id:
                cluster_trace_data.append(
                    {
                        "trace_id": trace_ids[i],
                        "distance_to_centroid": float(distances_matrix[i][cluster_id]),
                    }
                )

        # Sort traces by distance to centroid to determine rank
        cluster_trace_data.sort(key=lambda x: x["distance_to_centroid"])

        # Build traces dict keyed by trace_id
        traces_dict = {
            t["trace_id"]: {
                "distance_to_centroid": t["distance_to_centroid"],
                "rank": rank,
            }
            for rank, t in enumerate(cluster_trace_data)
        }

        # Get labels for this cluster (with fallback)
        if cluster_id in cluster_labels:
            title = cluster_labels[cluster_id].title
            description = cluster_labels[cluster_id].description
        else:
            title = f"Cluster {cluster_id}"
            description = ""

        clusters.append(
            ClusterData(
                cluster_id=cluster_id,
                size=len(traces_dict),
                title=title,
                description=description,
                traces=traces_dict,
                centroid=centroids[cluster_id],
            )
        )

    return clusters
