"""
Activity 6 of the video segment clustering workflow:
Persisting Tasks, TaskSegmentLinks, and updating the clustering state watermark.
"""

from datetime import datetime

from django.utils import timezone as django_timezone

import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.video_segment_clustering.models import (
    ClusterLabel,
    PersistTasksActivityInputs,
    PersistTasksResult,
)
from posthog.temporal.ai.video_segment_clustering.priority import calculate_priority_score, calculate_task_metrics

from products.tasks.backend.models import Task, TaskSegmentLink, VideoSegmentClusteringState

logger = structlog.get_logger(__name__)


@activity.defn
async def persist_tasks_activity(inputs: PersistTasksActivityInputs) -> PersistTasksResult:
    """Persist Tasks, create segment links, and update the clustering state watermark.

    Creates Task records for new clusters with LLM-generated labels.
    Updates existing Tasks with new segment data and recalculates priority.
    Creates TaskSegmentLink records for all processed segments.
    Updates VideoSegmentClusteringState with the latest processed timestamp.
    """
    team = await Team.objects.aget(id=inputs.team_id)

    segment_lookup = {s.document_id: s for s in inputs.segments}

    task_ids: list[str] = []
    tasks_created = 0
    tasks_updated = 0

    # Build cluster_to_task mapping as we create tasks
    cluster_to_task: dict[int, str] = {}

    # 1. Create new Tasks for new clusters
    for cluster in inputs.new_clusters:
        label = inputs.labels.get(cluster.cluster_id)
        if not label:
            label = ClusterLabel(
                title=f"Issue Cluster {cluster.cluster_id}",
                description="Automatically detected issue from video analysis.",
            )

        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]
        metrics = calculate_task_metrics(cluster_segments)

        priority = calculate_priority_score(
            distinct_user_count=metrics["distinct_user_count"],
        )

        task = await Task.objects.acreate(
            team=team,
            title=label.title,
            description=label.description,
            origin_product=Task.OriginProduct.SESSION_SUMMARIES,
            cluster_centroid=cluster.centroid,
            cluster_centroid_updated_at=django_timezone.now(),
            priority_score=priority,
            distinct_user_count=metrics["distinct_user_count"],
            occurrence_count=metrics["occurrence_count"],
            last_occurrence_at=metrics["last_occurrence_at"],
        )

        task_ids.append(str(task.id))
        cluster_to_task[cluster.cluster_id] = str(task.id)
        tasks_created += 1

        logger.info(
            "Created task from cluster",
            task_id=str(task.id),
            cluster_id=cluster.cluster_id,
            cluster_size=cluster.size,
        )

    # 2. Update existing Tasks for matched clusters
    for match in inputs.matched_clusters:
        try:
            task = await Task.objects.aget(id=match.task_id)
        except Task.DoesNotExist:
            logger.warning("Matched task not found", task_id=match.task_id)
            continue

        cluster_to_task[match.cluster_id] = match.task_id

        # Find segments for this matched cluster from segment_to_cluster
        matched_segment_ids = [doc_id for doc_id, cid in inputs.segment_to_cluster.items() if cid == match.cluster_id]
        cluster_segments = [segment_lookup[sid] for sid in matched_segment_ids if sid in segment_lookup]

        if cluster_segments:
            new_metrics = calculate_task_metrics(cluster_segments)

            task.distinct_user_count += new_metrics["distinct_user_count"]
            task.occurrence_count += new_metrics["occurrence_count"]

            if new_metrics["last_occurrence_at"]:
                if task.last_occurrence_at is None or new_metrics["last_occurrence_at"] > task.last_occurrence_at:
                    task.last_occurrence_at = new_metrics["last_occurrence_at"]

            task.priority_score = calculate_priority_score(
                distinct_user_count=task.distinct_user_count,
            )

            await task.asave()
            tasks_updated += 1

            logger.info(
                "Updated task from matched cluster",
                task_id=str(task.id),
                cluster_id=match.cluster_id,
                new_segments=len(cluster_segments),
            )

        task_ids.append(str(task.id))

    # 3. Create TaskSegmentLink records
    links_created = 0

    for segment in inputs.segments:
        cluster_id = inputs.segment_to_cluster.get(segment.document_id)
        if cluster_id is None:
            continue

        task_id = cluster_to_task.get(cluster_id)
        if not task_id:
            continue

        try:
            task = await Task.objects.aget(id=task_id)
        except Task.DoesNotExist:
            continue

        segment_timestamp = None
        if segment.timestamp:
            try:
                segment_timestamp = datetime.fromisoformat(segment.timestamp.replace("Z", "+00:00"))
            except ValueError:
                pass

        await TaskSegmentLink.objects.aupdate_or_create(
            task=task,
            session_id=segment.session_id,
            segment_start_time=segment.start_time,
            segment_end_time=segment.end_time,
            defaults={
                "team": team,
                "distinct_id": segment.distinct_id,
                "content": segment.content[:1000],
                "distance_to_centroid": None,
                "segment_timestamp": segment_timestamp,
            },
        )
        links_created += 1

    # 4. Update clustering state watermark
    watermark_updated = False
    if inputs.latest_timestamp:
        try:
            latest_ts = datetime.fromisoformat(inputs.latest_timestamp.replace("Z", "+00:00"))
            await VideoSegmentClusteringState.objects.aupdate_or_create(
                team=team,
                defaults={
                    "last_processed_at": latest_ts,
                    "segments_processed": len(inputs.segments),
                },
            )
            watermark_updated = True
        except Exception as e:
            logger.warning("Failed to update clustering state", error=str(e))

    return PersistTasksResult(
        tasks_created=tasks_created,
        tasks_updated=tasks_updated,
        task_ids=task_ids,
        links_created=links_created,
        watermark_updated=watermark_updated,
    )
