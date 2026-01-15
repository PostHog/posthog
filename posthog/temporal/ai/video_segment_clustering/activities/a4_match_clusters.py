"""
Activity 4 of the video segment clustering workflow:
Matching clusters to existing tasks.
"""

import numpy as np
from sklearn.metrics.pairwise import cosine_distances
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    MatchClustersActivityInputs,
    MatchingResult,
    TaskMatch,
)

from products.tasks.backend.models import Task


@activity.defn
async def match_clusters_activity(inputs: MatchClustersActivityInputs) -> MatchingResult:
    """Match new clusters to existing Tasks.

    Compares cluster centroids to existing Task centroids using cosine distance.
    Clusters within threshold are matched, others become new Tasks.
    """
    team = await Team.objects.aget(id=inputs.team_id)
    existing_task_centroids = await _fetch_existing_task_centroids(team)

    if not existing_task_centroids:
        # No existing tasks, all clusters are new
        return MatchingResult(
            new_clusters=inputs.clusters,
            matched_clusters=[],
        )

    new_clusters: list[Cluster] = []
    matched_clusters: list[TaskMatch] = []

    # Convert task centroids to arrays for efficient comparison
    task_ids = list(existing_task_centroids.keys())
    task_centroids = np.array(list(existing_task_centroids.values()))

    for cluster in inputs.clusters:
        cluster_centroid = np.array(cluster.centroid).reshape(1, -1)
        # Calculate cosine distances to all task centroids
        distances = cosine_distances(cluster_centroid, task_centroids)[0]
        # Find best match
        min_idx = np.argmin(distances)
        min_distance = distances[min_idx]
        if min_distance < constants.TASK_MATCH_THRESHOLD:
            # Found a match based on centroid similarity
            # Note: This is pretty crude, as we're relying purely on the stability of clustering, and aren't
            # comparing the descriptions in a semantic way per se. For a semantic comparison, an LLM could be
            # a robust verifier, but the cost would increase significantly.
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


async def _fetch_existing_task_centroids(team: Team) -> dict[str, list[float]]:
    """Fetch cluster centroids from existing Tasks for deduplication.

    Args:
        team: Team object

    Returns:
        Dictionary mapping task_id -> centroid embedding
    """
    result: dict[str, list[float]] = {}
    async for task in Task.objects.filter(
        team=team,
        origin_product=Task.OriginProduct.SESSION_SUMMARIES,
        deleted=False,
        cluster_centroid__isnull=False,
    ).values("id", "cluster_centroid"):
        result[str(task["id"])] = task["cluster_centroid"]
    return result
