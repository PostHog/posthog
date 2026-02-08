"""
Activity 4 of the video segment clustering workflow:
Matching clusters to existing signal reports.
"""

import numpy as np
from sklearn.metrics.pairwise import cosine_distances
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.centroid_cache import get_centroids, get_workflow_id_from_activity
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    MatchClustersActivityInputs,
    MatchingResult,
    ReportMatch,
)

from products.signals.backend.models import SignalReport


@activity.defn
async def match_clusters_activity(inputs: MatchClustersActivityInputs) -> MatchingResult:
    """Match new clusters to existing SignalReports.

    Compares cluster centroids to existing report centroids using cosine distance.
    Clusters within threshold are matched, others become new reports.

    Centroids are fetched from Redis (stored by the clustering activity).
    """
    # Fetch cluster centroids from Redis
    workflow_id = get_workflow_id_from_activity()
    cached_centroids = await get_centroids(workflow_id)
    if cached_centroids is None:
        raise ValueError("Centroids not found in cache - clustering activity may not have run")

    team = await Team.objects.aget(id=inputs.team_id)
    existing_report_centroids = await _fetch_existing_report_centroids(team)

    if not existing_report_centroids:
        # No existing reports, all clusters are new
        return MatchingResult(
            new_clusters=inputs.clusters,
            matched_clusters=[],
        )

    new_clusters: list[Cluster] = []
    matched_clusters: list[ReportMatch] = []

    # Convert report centroids to arrays for efficient comparison
    report_ids = list(existing_report_centroids.keys())
    report_centroids = np.array(list(existing_report_centroids.values()))

    for cluster in inputs.clusters:
        centroid = cached_centroids.get(cluster.cluster_id)
        if centroid is None:
            # Should not happen, but be defensive
            new_clusters.append(cluster)
            continue
        cluster_centroid = np.array(centroid).reshape(1, -1)
        # Calculate cosine distances to all report centroids
        distances = cosine_distances(cluster_centroid, report_centroids)[0]
        # Find best match
        min_idx = np.argmin(distances)
        min_distance = distances[min_idx]
        if min_distance < constants.TASK_MATCH_THRESHOLD:
            # Found a match based on centroid similarity
            # Note: This is pretty crude, as we're relying purely on the stability of clustering, and aren't
            # comparing the descriptions in a semantic way per se. For a semantic comparison, an LLM could be
            # a robust verifier, but the cost would increase significantly.
            matched_clusters.append(
                ReportMatch(
                    cluster_id=cluster.cluster_id,
                    report_id=report_ids[min_idx],
                    distance=float(min_distance),
                )
            )
        else:
            # No match, this is a new cluster
            new_clusters.append(cluster)

    return MatchingResult(
        new_clusters=new_clusters,
        matched_clusters=matched_clusters,
    )


async def _fetch_existing_report_centroids(team: Team) -> dict[str, list[float]]:
    """Fetch cluster centroids from existing SignalReports for deduplication.

    Args:
        team: Team object

    Returns:
        Dictionary mapping report_id -> centroid embedding
    """
    result: dict[str, list[float]] = {}
    async for report in SignalReport.objects.filter(
        team=team,
        status=SignalReport.Status.READY,
        cluster_centroid__isnull=False,
    ).values("id", "cluster_centroid"):
        centroid = report["cluster_centroid"]
        assert centroid is not None  # Filtered by cluster_centroid__isnull=False
        result[str(report["id"])] = centroid
    return result
