"""Emit $ai_evaluation_clusters events after Stage B clustering.

Parallel to ``trace_clustering.event_emission.emit_cluster_events`` — reuses the
shared ``_build_cluster_data`` helper for the actual cluster-data assembly — but
with two eval-specific differences:

1. Event name: ``$ai_evaluation_clusters``.
2. No trace-summary fetch: eval events have no summary table; we already carry
   per-eval timestamps via the metadata join done upstream.
"""

import uuid
import dataclasses

import numpy as np

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.temporal.llm_analytics.evaluation_clustering.constants import EVENT_NAME_EVALUATION_CLUSTERS
from posthog.temporal.llm_analytics.trace_clustering.event_emission import _build_cluster_data
from posthog.temporal.llm_analytics.trace_clustering.models import (
    ClusterAggregateMetrics,
    ClusterData,
    ClusteringParams,
    ClusterItem,
    ClusterLabel,
)


def emit_evaluation_cluster_events(
    team_id: int,
    clustering_run_id: str,
    window_start: str,
    window_end: str,
    labels: list[int],
    centroids: list[list[float]],
    items: list[ClusterItem],
    distances_matrix: np.ndarray,
    cluster_labels: dict[int, ClusterLabel],
    coords_2d: np.ndarray,
    centroid_coords_2d: np.ndarray,
    item_timestamps: dict[str, str],
    clustering_params: ClusteringParams | None = None,
    job_id: str = "",
    job_name: str = "",
    cluster_metrics: dict[int, ClusterAggregateMetrics] | None = None,
) -> list[ClusterData]:
    """Emit a single $ai_evaluation_clusters event carrying all cluster data.

    ``item_timestamps`` must be prefilled by the caller — Stage B's metadata
    query already carries the needed timestamps, so we avoid a second events
    table lookup here.
    """
    team = Team.objects.get(id=team_id)
    num_clusters = len(centroids)

    clusters = _build_cluster_data(
        num_clusters=num_clusters,
        labels=labels,
        items=items,
        distances_matrix=distances_matrix,
        centroids=centroids,
        cluster_labels=cluster_labels,
        coords_2d=coords_2d,
        centroid_coords_2d=centroid_coords_2d,
        item_timestamps=item_timestamps,
        cluster_metrics=cluster_metrics or {},
    )

    properties: dict = {
        "$ai_clustering_run_id": clustering_run_id,
        "$ai_clustering_level": "evaluation",
        "$ai_clustering_job_id": job_id,
        "$ai_clustering_job_name": job_name,
        "$ai_window_start": window_start,
        "$ai_window_end": window_end,
        "$ai_total_items_analyzed": len(items),
        "$ai_clusters": [dataclasses.asdict(c) for c in clusters],
    }

    if clustering_params:
        properties["$ai_clustering_params"] = dataclasses.asdict(clustering_params)

    create_event(
        event_uuid=uuid.uuid4(),
        event=EVENT_NAME_EVALUATION_CLUSTERS,
        team=team,
        distinct_id=f"clustering_evaluation_{team_id}",
        properties=properties,
    )

    return clusters
