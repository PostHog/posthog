"""Temporal activities for video segment clustering workflow.

Activities:
1. fetch_segments_activity - Fetch unprocessed video segments from ClickHouse
2. cluster_segments_activity - HDBSCAN clustering with PCA reduction
3. match_clusters_activity - Match new clusters to existing Tasks
4. generate_labels_activity - LLM-based label generation for new clusters
5. create_update_tasks_activity - Create new Tasks and update existing ones
6. link_segments_activity - Link segments to Tasks and update watermark
"""

import asyncio
from datetime import datetime

import numpy as np
import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.clustering import (
    calculate_cosine_distance,
    match_clusters_to_existing_tasks,
    perform_hdbscan_clustering,
    update_task_centroid,
)
from posthog.temporal.ai.video_segment_clustering.data import fetch_existing_task_centroids, fetch_video_segments
from posthog.temporal.ai.video_segment_clustering.models import (
    ClusteringResult,
    ClusterLabel,
    CreateUpdateTasksActivityInputs,
    FetchSegmentsActivityInputs,
    FetchSegmentsResult,
    GenerateLabelsActivityInputs,
    LabelingResult,
    LinkingResult,
    LinkSegmentsActivityInputs,
    MatchClustersActivityInputs,
    MatchingResult,
    TaskCreationResult,
    VideoSegment,
)
from posthog.temporal.ai.video_segment_clustering.priority import calculate_priority_score, calculate_task_metrics

logger = structlog.get_logger(__name__)


# Activity 1: Fetch segments
def _fetch_segments(inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Fetch video segments from ClickHouse."""
    team = Team.objects.get(id=inputs.team_id)

    since_timestamp = None
    if inputs.since_timestamp:
        since_timestamp = datetime.fromisoformat(inputs.since_timestamp.replace("Z", "+00:00"))

    return fetch_video_segments(
        team=team,
        since_timestamp=since_timestamp,
        lookback_hours=inputs.lookback_hours,
    )


@activity.defn
async def fetch_segments_activity(inputs: FetchSegmentsActivityInputs) -> FetchSegmentsResult:
    """Activity 1: Fetch unprocessed video segments from ClickHouse.

    Queries document_embeddings for video segments that haven't been processed yet,
    based on the clustering state watermark.
    """
    return await asyncio.to_thread(_fetch_segments, inputs)


# Activity 2: Cluster segments
def _cluster_segments(segments: list[VideoSegment]) -> ClusteringResult:
    """Run HDBSCAN clustering on segments."""
    return perform_hdbscan_clustering(segments)


@activity.defn
async def cluster_segments_activity(segments: list[VideoSegment]) -> ClusteringResult:
    """Activity 2: Cluster video segments using HDBSCAN.

    Applies PCA dimensionality reduction then HDBSCAN clustering.
    Returns clusters with centroids computed from original embeddings.
    """
    return await asyncio.to_thread(_cluster_segments, segments)


# Activity 3: Match clusters to existing tasks
def _match_clusters(inputs: MatchClustersActivityInputs) -> MatchingResult:
    """Match clusters to existing tasks."""
    team = Team.objects.get(id=inputs.team_id)
    existing_centroids = fetch_existing_task_centroids(team)

    return match_clusters_to_existing_tasks(
        clusters=inputs.clusters,
        existing_task_centroids=existing_centroids,
    )


@activity.defn
async def match_clusters_activity(inputs: MatchClustersActivityInputs) -> MatchingResult:
    """Activity 3: Match new clusters to existing Tasks.

    Compares cluster centroids to existing Task centroids using cosine distance.
    Clusters within threshold are matched; others become new Tasks.
    """
    return await asyncio.to_thread(_match_clusters, inputs)


# Activity 4: Generate labels
async def _generate_labels(inputs: GenerateLabelsActivityInputs) -> LabelingResult:
    """Generate LLM labels for clusters."""
    from posthog.temporal.ai.video_segment_clustering.labeling import generate_cluster_labels_llm

    # Build segment lookup
    segment_lookup = {s.document_id: s for s in inputs.segments}

    labels: dict[int, ClusterLabel] = {}

    for cluster in inputs.clusters:
        # Get segment contents for this cluster
        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]

        if not cluster_segments:
            # Fallback label
            labels[cluster.cluster_id] = ClusterLabel(
                title=f"Issue Cluster {cluster.cluster_id}",
                description="A group of similar video segment issues.",
            )
            continue

        # Generate label using LLM
        try:
            label = await generate_cluster_labels_llm(
                team_id=inputs.team_id,
                segments=cluster_segments[: constants.DEFAULT_SEGMENTS_PER_CLUSTER_FOR_LABELING],
            )
            labels[cluster.cluster_id] = label
        except Exception as e:
            logger.warning(
                "Failed to generate LLM label for cluster",
                cluster_id=cluster.cluster_id,
                error=str(e),
            )
            # Fallback
            labels[cluster.cluster_id] = ClusterLabel(
                title=f"Issue: {cluster_segments[0].content[:50]}...",
                description=cluster_segments[0].content[:200],
            )

    return LabelingResult(labels=labels)


@activity.defn
async def generate_labels_activity(inputs: GenerateLabelsActivityInputs) -> LabelingResult:
    """Activity 4: Generate LLM-based labels for new clusters, i.e. actionable task titles and descriptions."""
    return await _generate_labels(inputs)


# Activity 5: Create/update tasks
def _create_update_tasks(inputs: CreateUpdateTasksActivityInputs) -> TaskCreationResult:
    """Create new Tasks and update existing ones."""
    from django.utils import timezone as django_timezone

    from products.tasks.backend.models import Task

    team = Team.objects.get(id=inputs.team_id)

    # Build segment lookup by document_id
    segment_lookup = {swi.segment.document_id: swi for swi in inputs.segments_with_impact}

    task_ids: list[str] = []
    tasks_created = 0
    tasks_updated = 0

    # Create new Tasks for new clusters
    for cluster in inputs.new_clusters:
        label = inputs.labels.get(cluster.cluster_id)
        if not label:
            label = ClusterLabel(
                title=f"Issue Cluster {cluster.cluster_id}",
                description="Automatically detected issue from video analysis.",
            )

        # Get segments for this cluster
        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]

        # Calculate metrics
        metrics = calculate_task_metrics(cluster_segments)

        # Calculate priority
        priority = calculate_priority_score(
            distinct_user_count=metrics["distinct_user_count"],
            avg_impact_score=metrics["avg_impact_score"],
            last_occurrence=metrics["last_occurrence_at"],
        )

        task = Task.objects.create(
            team=team,
            title=label.title,
            description=label.description,
            origin_product=Task.OriginProduct.SESSION_SUMMARIES,
            cluster_centroid=cluster.centroid,
            cluster_centroid_updated_at=django_timezone.now(),
            priority_score=priority,
            distinct_user_count=metrics["distinct_user_count"],
            occurrence_count=metrics["occurrence_count"],
            avg_impact_score=metrics["avg_impact_score"],
            last_occurrence_at=metrics["last_occurrence_at"],
        )

        task_ids.append(str(task.id))
        tasks_created += 1

        logger.info(
            "Created task from cluster",
            task_id=str(task.id),
            cluster_id=cluster.cluster_id,
            cluster_size=cluster.size,
        )

    # Update existing Tasks for matched clusters
    for match in inputs.matched_clusters:
        try:
            task = Task.objects.get(id=match.task_id)
        except Task.DoesNotExist:
            logger.warning("Matched task not found", task_id=match.task_id)
            continue

        # Find the cluster for this match
        matched_cluster = None
        for cluster in inputs.new_clusters:
            if cluster.cluster_id == match.cluster_id:
                matched_cluster = cluster
                break

        if not matched_cluster:
            task_ids.append(str(task.id))
            continue

        # Get segments for this cluster
        cluster_segments = [segment_lookup[sid] for sid in matched_cluster.segment_ids if sid in segment_lookup]

        # Update centroid
        new_embeddings = np.array([swi.segment.embedding for swi in cluster_segments])
        updated_centroid = update_task_centroid(
            existing_centroid=task.cluster_centroid,
            existing_count=task.occurrence_count,
            new_embeddings=new_embeddings,
        )

        # Recalculate metrics including new segments
        new_metrics = calculate_task_metrics(cluster_segments)

        # Update counts (additive)
        task.distinct_user_count += new_metrics["distinct_user_count"]  # May overcount
        task.occurrence_count += new_metrics["occurrence_count"]

        # Update average impact (weighted)
        total_count = task.occurrence_count
        if total_count > 0:
            old_weight = (task.occurrence_count - new_metrics["occurrence_count"]) / total_count
            new_weight = new_metrics["occurrence_count"] / total_count
            task.avg_impact_score = task.avg_impact_score * old_weight + new_metrics["avg_impact_score"] * new_weight

        # Update last occurrence
        if new_metrics["last_occurrence_at"]:
            if task.last_occurrence_at is None or new_metrics["last_occurrence_at"] > task.last_occurrence_at:
                task.last_occurrence_at = new_metrics["last_occurrence_at"]

        # Update centroid
        task.cluster_centroid = updated_centroid
        task.cluster_centroid_updated_at = django_timezone.now()

        # Recalculate priority
        task.priority_score = calculate_priority_score(
            distinct_user_count=task.distinct_user_count,
            avg_impact_score=task.avg_impact_score,
            last_occurrence=task.last_occurrence_at,
        )

        task.save()
        task_ids.append(str(task.id))
        tasks_updated += 1

        logger.info(
            "Updated task from matched cluster",
            task_id=str(task.id),
            cluster_id=match.cluster_id,
            new_segments=len(cluster_segments),
        )

    return TaskCreationResult(
        tasks_created=tasks_created,
        tasks_updated=tasks_updated,
        task_ids=task_ids,
    )


@activity.defn
async def create_update_tasks_activity(inputs: CreateUpdateTasksActivityInputs) -> TaskCreationResult:
    """Activity 5: Create new Tasks and update existing ones.

    Creates Task records for new clusters with LLM-generated labels.
    Updates existing Tasks with new segment data and recalculates priority.
    """
    return await asyncio.to_thread(_create_update_tasks, inputs)


# Activity 6: Link segments to tasks
def _link_segments(inputs: LinkSegmentsActivityInputs) -> LinkingResult:
    """Create TaskSegmentLink records and update clustering state."""

    from products.tasks.backend.models import Task, TaskSegmentLink, VideoSegmentClusteringState

    team = Team.objects.get(id=inputs.team_id)

    links_created = 0

    for swi in inputs.segments_with_impact:
        segment = swi.segment
        cluster_id = inputs.segment_to_cluster.get(segment.document_id)

        if cluster_id is None:
            # Noise segment, skip
            continue

        task_id = inputs.cluster_to_task.get(cluster_id)
        if not task_id:
            continue

        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            continue

        # Calculate distance to centroid
        distance = None
        if task.cluster_centroid:
            distance = calculate_cosine_distance(segment.embedding, task.cluster_centroid)

        # Parse timestamp
        segment_timestamp = None
        if segment.timestamp:
            try:
                segment_timestamp = datetime.fromisoformat(segment.timestamp.replace("Z", "+00:00"))
            except ValueError:
                pass

        # Create link (or update if exists)
        TaskSegmentLink.objects.update_or_create(
            task=task,
            session_id=segment.session_id,
            segment_start_time=segment.start_time,
            segment_end_time=segment.end_time,
            defaults={
                "team": team,
                "distinct_id": segment.distinct_id,
                "content": segment.content[:1000],  # Truncate if too long
                "impact_score": swi.impact_score,
                "failure_detected": swi.impact_flags.get("failure_detected", False),
                "confusion_detected": swi.impact_flags.get("confusion_detected", False),
                "abandonment_detected": swi.impact_flags.get("abandonment_detected", False),
                "distance_to_centroid": distance,
                "segment_timestamp": segment_timestamp,
            },
        )
        links_created += 1

    # Update clustering state
    watermark_updated = False
    if inputs.latest_timestamp:
        try:
            latest_ts = datetime.fromisoformat(inputs.latest_timestamp.replace("Z", "+00:00"))
            state, _ = VideoSegmentClusteringState.objects.update_or_create(
                team=team,
                defaults={
                    "last_processed_at": latest_ts,
                    "segments_processed": len(inputs.segments_with_impact),
                },
            )
            watermark_updated = True
        except Exception as e:
            logger.warning("Failed to update clustering state", error=str(e))

    return LinkingResult(
        links_created=links_created,
        watermark_updated=watermark_updated,
    )


@activity.defn
async def link_segments_activity(inputs: LinkSegmentsActivityInputs) -> LinkingResult:
    """Activity 6: Link segments to Tasks and update watermark.

    Creates TaskSegmentLink records for all processed segments.
    Updates VideoSegmentClusteringState with the latest processed timestamp.
    """
    return await asyncio.to_thread(_link_segments, inputs)
