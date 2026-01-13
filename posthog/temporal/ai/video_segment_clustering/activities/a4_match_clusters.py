"""
Activity 4 of the video segment clustering workflow:
Matching clusters to existing tasks.
"""

import numpy as np
from sklearn.metrics.pairwise import cosine_distances
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.data import fetch_existing_task_centroids
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    MatchClustersActivityInputs,
    MatchingResult,
    TaskMatch,
)


def match_clusters_to_existing_tasks(
    clusters: list[Cluster],
    existing_task_centroids: dict[str, list[float]],
    match_threshold: float = constants.TASK_MATCH_THRESHOLD,
) -> MatchingResult:
    """Match new clusters to existing Tasks based on centroid similarity.

    Args:
        clusters: List of new clusters from HDBSCAN
        existing_task_centroids: Dict mapping task_id -> centroid embedding
        match_threshold: Maximum cosine distance to consider a match

    Returns:
        MatchingResult with new clusters and matched clusters
    """
    if not existing_task_centroids:
        # No existing tasks, all clusters are new
        return MatchingResult(
            new_clusters=clusters,
            matched_clusters=[],
        )

    new_clusters: list[Cluster] = []
    matched_clusters: list[TaskMatch] = []

    # Convert task centroids to arrays for efficient comparison
    task_ids = list(existing_task_centroids.keys())
    task_centroids = np.array(list(existing_task_centroids.values()))

    for cluster in clusters:
        cluster_centroid = np.array(cluster.centroid).reshape(1, -1)

        # Calculate cosine distances to all task centroids
        distances = cosine_distances(cluster_centroid, task_centroids)[0]

        # Find best match
        min_idx = np.argmin(distances)
        min_distance = distances[min_idx]

        if min_distance < match_threshold:
            # Found a match
            matched_clusters.append(
                TaskMatch(
                    cluster_id=cluster.cluster_id,
                    task_id=task_ids[min_idx],
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


@activity.defn
async def match_clusters_activity(inputs: MatchClustersActivityInputs) -> MatchingResult:
    """Match new clusters to existing Tasks.

    Compares cluster centroids to existing Task centroids using cosine distance.
    Clusters within threshold are matched; others become new Tasks.
    """
    team = await Team.objects.aget(id=inputs.team_id)
    existing_centroids = await fetch_existing_task_centroids(team)

    return match_clusters_to_existing_tasks(
        clusters=inputs.clusters,
        existing_task_centroids=existing_centroids,
    )
