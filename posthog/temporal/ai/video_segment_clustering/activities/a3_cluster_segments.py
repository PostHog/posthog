"""
Activity 3 of the video segment clustering workflow:
Clustering video segments using iterative K-means, with noise handling.
"""

import json
import math
import asyncio
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import AgglomerativeClustering, KMeans
from sklearn.metrics.pairwise import cosine_distances
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.centroid_cache import get_workflow_id_from_activity, store_centroids
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    ClusteringResult,
    ClusterSegmentsActivityInputs,
    VideoSegment,
)
from posthog.temporal.common.logger import get_logger

from ..data import fetch_video_segment_embedding_rows

logger = get_logger(__name__)


@dataclass
class _ClusteringResultWithCentroids:
    """Internal result that includes centroids for Redis storage."""

    result: ClusteringResult
    centroids: dict[int, list[float]]


@activity.defn
async def cluster_segments_activity(inputs: ClusterSegmentsActivityInputs) -> ClusteringResult:
    """Cluster video segments by semantic similarity.

    Fetches embeddings from ClickHouse, then clusters them using one of two algorithms:

    For small-volume teams (segment count < 200): Agglomerative clustering
    - Builds clusters bottom-up by merging similar pairs
    - Naturally handles grouping 2-3 similar segments together
    - All segments are assigned to clusters (no noise)

    For medium-volume teams (segment count >= 200): Iterative K-means
    - Noise segments are converted to single-segment clusters

    For high-volume teams (segment count >= 1000): Iterative K-means
    - Noise segments remain as noise (not converted to Tasks)

    Iterative K-means steps:
    1. Estimate K using log scaling (K = KMEANS_K_MULTIPLIER * log10(n))
    2. Run K-means clustering with PCA dimensionality reduction
    3. For each cluster, check if it's "tight" (max cosine distance to centroid < threshold)
    4. Tight clusters are finalized, loose cluster segments go back to the pool
    5. Repeat until convergence or max iterations
    6. Remaining segments are marked as noise

    Centroids are stored in Redis (keyed by workflow ID) to avoid large Temporal payloads.
    """
    team = await Team.objects.aget(id=inputs.team_id)
    # We fetch segments here instead of passing via Temporal, to avoid large Temporal payloads (each embedding is 3 KB)
    segments = await _fetch_embeddings_by_document_ids(team, inputs.document_ids)

    # Run in to_thread as clustering is CPU-bound
    clustering_with_centroids = await asyncio.to_thread(_perform_clustering, segments)

    # Store centroids in Redis for downstream activities
    workflow_id = get_workflow_id_from_activity()
    await store_centroids(workflow_id, clustering_with_centroids.centroids)

    return clustering_with_centroids.result


async def _fetch_embeddings_by_document_ids(
    team: Team,
    document_ids: list[str],
) -> list[VideoSegment]:
    if not document_ids:
        return []

    rows = await fetch_video_segment_embedding_rows(team, document_ids)
    segments: list[VideoSegment] = []

    for row in rows:
        document_id, content, embedding, metadata_str, _timestamp_of_embedding = row
        try:
            metadata = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str
        except (json.JSONDecodeError, TypeError):
            # Being defensive to avoid a poison pill kind of situation
            logger.exception(f"Failed to parse metadata for document_id: {document_id}", metadata_str=metadata_str)
            continue
        session_id = metadata.get("session_id")
        start_time = metadata.get("start_time")
        end_time = metadata.get("end_time")
        distinct_id = metadata.get("distinct_id")
        session_start_time = metadata.get("session_start_time")
        session_end_time = metadata.get("session_end_time")
        session_duration = metadata.get("session_duration")
        session_active_seconds = metadata.get("session_active_seconds")
        if (
            not session_id
            or not start_time
            or not end_time
            or not distinct_id
            or not session_start_time
            or not session_end_time
            or not session_duration
            or not session_active_seconds
        ):
            logger.error(f"Missing required metadata for document_id: {document_id}", metadata=metadata)
            continue
        segments.append(
            VideoSegment(
                document_id=document_id,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
                session_start_time=session_start_time,
                session_end_time=session_end_time,
                session_duration=session_duration,
                session_active_seconds=session_active_seconds,
                distinct_id=distinct_id,
                content=content,
                embedding=embedding,
            )
        )

    return segments


def _perform_clustering(segments: list[VideoSegment]) -> _ClusteringResultWithCentroids:
    """Run clustering and handle noise. CPU-bound.

    Returns ClusteringResult with centroids stored separately for Redis caching.
    """
    n_segments = len(segments)

    if n_segments < constants.AGGLOMERATIVE_CLUSTERING_SEGMENT_THRESHOLD:
        result_with_centroids = _perform_agglomerative_clustering(segments)
    else:
        result_with_centroids = _perform_iterative_kmeans_clustering(segments)

    result = result_with_centroids.result
    centroids = result_with_centroids.centroids

    # For medium-volume teams, convert noise to single-segment clusters
    # For high-volume teams, keep noise as noise
    if n_segments < constants.NOISE_DISCARDING_SEGMENT_THRESHOLD and result.noise_segment_ids:
        # Handle noise segments by creating single-segment clusters
        max_cluster_id = max((c.cluster_id for c in result.clusters), default=-1)
        noise_result = _create_single_segment_clusters(
            noise_segment_ids=result.noise_segment_ids,
            all_segments=segments,
            cluster_id_offset=max_cluster_id + 1,
        )
        # Update result in place
        result.clusters += noise_result.clusters
        result.noise_segment_ids = []
        for cluster in noise_result.clusters:
            for doc_id in cluster.segment_ids:
                result.segment_to_cluster[doc_id] = cluster.cluster_id
        # Merge centroids
        centroids.update(noise_result.centroids)

    return _ClusteringResultWithCentroids(result=result, centroids=centroids)


def _estimate_k(n_segments: int, k_multiplier: float = constants.KMEANS_K_MULTIPLIER) -> int:
    """Estimate number of clusters based on segment count using log scaling.

    K scales with log(n) because most segments match existing issues probably, to be tested exactly),
    so unique clusters grow logarithmically, not linearly. This is an initial guess that gets iterated upon.
    """
    if n_segments <= 1:
        return max(2, n_segments)
    return max(2, int(k_multiplier * math.log10(n_segments)))


def _perform_iterative_kmeans_clustering(
    segments: list[VideoSegment],
    distance_threshold: float = constants.KMEANS_DISTANCE_THRESHOLD,
    max_iterations: int = constants.KMEANS_MAX_ITERATIONS,
    min_cluster_size: int = constants.MIN_CLUSTER_SIZE,
    k_multiplier: float = constants.KMEANS_K_MULTIPLIER,
) -> _ClusteringResultWithCentroids:
    if len(segments) == 0:
        logger.debug("Iterative K-means clustering: no segments provided, returning empty result")
        return _ClusteringResultWithCentroids(
            result=ClusteringResult(
                clusters=[],
                noise_segment_ids=[],
                labels=[],
                segment_to_cluster={},
            ),
            centroids={},
        )

    n_segments = len(segments)
    logger.debug(
        "Starting iterative K-means clustering",
        n_segments=n_segments,
        distance_threshold=distance_threshold,
        max_iterations=max_iterations,
        min_cluster_size=min_cluster_size,
        k_multiplier=k_multiplier,
    )

    all_embeddings = np.array([s.embedding for s in segments])
    all_document_ids = [s.document_id for s in segments]

    # Mapping from document_id to index
    doc_id_to_idx = {doc_id: idx for idx, doc_id in enumerate(all_document_ids)}

    # Track which segments are still in the pool
    remaining_doc_ids = set(all_document_ids)
    final_clusters: list[Cluster] = []
    centroids: dict[int, list[float]] = {}  # Stored separately for Redis caching

    iteration = 0
    # TODO: Explore progressive threshold relaxation, i.e. larger distance threshold in later
    # iterations to group more outliers (similar to LLM traces clustering approach)
    while len(remaining_doc_ids) >= min_cluster_size and iteration < max_iterations:
        iteration += 1
        n_remaining = len(remaining_doc_ids)

        # Get embeddings for remaining segments
        remaining_indices = [doc_id_to_idx[doc_id] for doc_id in remaining_doc_ids]
        remaining_embeddings = all_embeddings[remaining_indices]
        remaining_ids = list(remaining_doc_ids)

        # Estimate K, capping at count of remaining segments
        k = min(_estimate_k(n_remaining, k_multiplier), n_remaining)

        logger.debug(
            "K-means iteration start",
            iteration=iteration,
            n_remaining=n_remaining,
            k=k,
            n_finalized_clusters=len(final_clusters),
        )

        try:
            # TODO: Consider using MiniBatchKMeans when n_remaining > 5000 for perf at scale
            kmeans = KMeans(n_clusters=k, random_state=42)  # Static random seed for reproducibility
            labels = kmeans.fit_predict(remaining_embeddings)
        except Exception as e:
            logger.exception(
                "K-means fitting failed",
                iteration=iteration,
                n_remaining=n_remaining,
                k=k,
                error=str(e),
            )
            break

        # Evaluate each cluster
        new_remaining: set[str] = set()
        tight_clusters_count = 0
        loose_clusters_count = 0
        for cluster_label in range(k):
            # Cluster label = cluster index, each segment being mapped to a cluster. Example of `labels` content:
            # For 8 samples clustered into k=3, `labels` is `np.array([0, 2, 1, 0, 2, 2, 1, 0])`
            cluster_mask = labels == cluster_label
            cluster_indices = np.where(cluster_mask)[0]

            if len(cluster_indices) == 0:
                continue

            cluster_doc_ids = [remaining_ids[i] for i in cluster_indices]
            cluster_embeddings = remaining_embeddings[cluster_indices]

            centroid = np.mean(cluster_embeddings, axis=0)

            # Compute cosine distances to centroid
            distances = cosine_distances(cluster_embeddings, centroid.reshape(1, -1)).flatten()
            near_max_dist = float(np.percentile(distances, 95))  # 95th percentile to be robust against outliers

            if near_max_dist < distance_threshold:
                # Tight cluster - finalize it
                cluster_id = len(final_clusters)
                final_clusters.append(
                    Cluster(
                        cluster_id=cluster_id,
                        segment_ids=cluster_doc_ids,
                        size=len(cluster_doc_ids),
                    )
                )
                centroids[cluster_id] = centroid.tolist()
                # Remove from remaining
                remaining_doc_ids -= set(cluster_doc_ids)
                tight_clusters_count += 1
            else:
                # Loose cluster - segments stay in pool for next iteration
                # TODO: Suggestion from Claude - instead of discarding the whole cluster, extract the "tight core"
                # (segments within a certain threshold) as a finalized cluster, and only return outliers to the pool.
                # Can avoid wasting computation on clusters that have a good core with few outliers.
                new_remaining.update(cluster_doc_ids)
                loose_clusters_count += 1

        logger.debug(
            "K-means iteration complete",
            iteration=iteration,
            tight_clusters=tight_clusters_count,
            loose_clusters=loose_clusters_count,
            segments_finalized=n_remaining - len(new_remaining),
            segments_remaining=len(new_remaining),
        )

        # Early exit if no progress (all clusters were loose)
        if len(new_remaining) == n_remaining:
            logger.debug(
                "Clustering stopped: no progress made in iteration",
                iteration=iteration,
                n_remaining=n_remaining,
            )
            break

        # Update remaining for next iteration
        remaining_doc_ids = new_remaining

    # Check exit conditions
    if iteration >= max_iterations:
        logger.debug(
            "Clustering stopped: reached max iterations",
            iteration=iteration,
            max_iterations=max_iterations,
            n_remaining=len(remaining_doc_ids),
        )
    elif len(remaining_doc_ids) < min_cluster_size:
        logger.debug(
            "Clustering stopped: remaining segments below minimum cluster size",
            iteration=iteration,
            n_remaining=len(remaining_doc_ids),
            min_cluster_size=min_cluster_size,
        )

    # Build segment_to_cluster mapping
    segment_to_cluster: dict[str, int] = {}
    for cluster in final_clusters:
        for doc_id in cluster.segment_ids:
            segment_to_cluster[doc_id] = cluster.cluster_id

    # Build labels list (in original order)
    labels_list = []
    for doc_id in all_document_ids:
        if doc_id in segment_to_cluster:
            labels_list.append(segment_to_cluster[doc_id])
        else:
            labels_list.append(-1)  # Noise

    n_noise = len(remaining_doc_ids)
    logger.debug(
        "Iterative K-means clustering complete",
        total_iterations=iteration,
        n_final_clusters=len(final_clusters),
        n_noise_segments=n_noise,
        n_clustered_segments=n_segments - n_noise,
        clustering_rate=(n_segments - n_noise) / n_segments if n_segments > 0 else 0.0,
    )

    return _ClusteringResultWithCentroids(
        result=ClusteringResult(
            clusters=final_clusters,
            noise_segment_ids=list(remaining_doc_ids),
            labels=labels_list,
            segment_to_cluster=segment_to_cluster,
        ),
        centroids=centroids,
    )


@dataclass
class _SingleSegmentClustersResult:
    """Internal result for noise cluster creation."""

    clusters: list[Cluster]
    centroids: dict[int, list[float]]


def _create_single_segment_clusters(
    *,
    noise_segment_ids: list[str],
    all_segments: list[VideoSegment],
    cluster_id_offset: int,
) -> _SingleSegmentClustersResult:
    segment_lookup = {s.document_id: s for s in all_segments}
    new_clusters: list[Cluster] = []
    centroids: dict[int, list[float]] = {}
    for i, doc_id in enumerate(noise_segment_ids):
        segment = segment_lookup.get(doc_id)
        if not segment:
            logger.error(f"Segment not found for document_id: {doc_id}")
            continue
        cluster_id = cluster_id_offset + i
        new_clusters.append(
            Cluster(
                cluster_id=cluster_id,
                segment_ids=[doc_id],
                size=1,
            )
        )
        centroids[cluster_id] = segment.embedding  # Single segment = its embedding is the centroid
    return _SingleSegmentClustersResult(clusters=new_clusters, centroids=centroids)


def _perform_agglomerative_clustering(
    segments: list[VideoSegment],
    cosine_distance_threshold: float = constants.KMEANS_DISTANCE_THRESHOLD,
) -> _ClusteringResultWithCentroids:
    if len(segments) == 0:
        return _ClusteringResultWithCentroids(
            result=ClusteringResult(
                clusters=[],
                noise_segment_ids=[],
                labels=[],
                segment_to_cluster={},
            ),
            centroids={},
        )

    all_embeddings = np.array([s.embedding for s in segments])
    all_document_ids = [s.document_id for s in segments]

    # Compute pairwise cosine distance matrix
    distance_matrix = cosine_distances(all_embeddings)

    # sklearn agglomerative clustering with distance threshold
    # - metric='precomputed': we provide the distance matrix
    # - linkage='complete': complete linkage, the distance within cluster is the maximum distance between any two points
    # - distance_threshold: max distance to merge clusters
    # - n_clusters=None: let the algorithm determine cluster count based on threshold
    clustering = AgglomerativeClustering(
        metric="precomputed",
        linkage="complete",
        distance_threshold=cosine_distance_threshold,
        n_clusters=None,
    )
    labels = clustering.fit_predict(distance_matrix)

    # Build clusters
    clusters: list[Cluster] = []
    centroids: dict[int, list[float]] = {}
    segment_to_cluster: dict[str, int] = {}

    unique_labels = set(labels)
    for label in unique_labels:
        cluster_indices = np.where(labels == label)[0]
        cluster_doc_ids = [all_document_ids[i] for i in cluster_indices]
        cluster_embeddings = all_embeddings[cluster_indices]

        # Compute centroid
        centroid = np.mean(cluster_embeddings, axis=0)

        cluster_id = int(label)
        clusters.append(
            Cluster(
                cluster_id=cluster_id,
                segment_ids=cluster_doc_ids,
                size=len(cluster_doc_ids),
            )
        )
        centroids[cluster_id] = centroid.tolist()

        for doc_id in cluster_doc_ids:
            segment_to_cluster[doc_id] = cluster_id

    # Build labels list in original order
    labels_list = [int(labels[i]) for i in range(len(all_document_ids))]

    return _ClusteringResultWithCentroids(
        result=ClusteringResult(
            clusters=clusters,
            noise_segment_ids=[],  # Agglomerative assigns all segments to clusters
            labels=labels_list,
            segment_to_cluster=segment_to_cluster,
        ),
        centroids=centroids,
    )
