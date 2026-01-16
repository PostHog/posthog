"""
Activity 6 of the video segment clustering workflow:
Persisting Tasks and TaskReferences.
"""

from datetime import datetime, timedelta

from django.utils import timezone as django_timezone

import structlog
from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.team import Team
from posthog.temporal.ai.session_summary.activities.a3_analyze_video_segment import _parse_timestamp_to_seconds
from posthog.temporal.ai.video_segment_clustering.data import count_distinct_persons
from posthog.temporal.ai.video_segment_clustering.models import PersistTasksActivityInputs, PersistTasksResult
from posthog.temporal.ai.video_segment_clustering.priority import calculate_priority_score, calculate_task_metrics

from products.tasks.backend.models import Task, TaskReference

logger = structlog.get_logger(__name__)


@activity.defn
async def persist_tasks_activity(inputs: PersistTasksActivityInputs) -> PersistTasksResult:
    """Persists new Tasks and updates existing relevant ones, creating TaskReferences in the process."""
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
            logger.warning("No label found for new cluster, skipping", cluster_id=cluster.cluster_id)
            continue

        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]
        metrics = await calculate_task_metrics(team, cluster_segments)

        priority = calculate_priority_score(
            relevant_user_count=metrics["relevant_user_count"],
        )

        task = await Task.objects.acreate(
            team=team,
            title=label.title,
            description=label.description,
            origin_product=Task.OriginProduct.SESSION_SUMMARIES,
            cluster_centroid=cluster.centroid,
            cluster_centroid_updated_at=django_timezone.now(),
            priority_score=priority,
            relevant_user_count=metrics["relevant_user_count"],
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

    # 2. Update existing Tasks for matched clusters (idempotent - only count new segments)
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
            # Check which segments already have TaskReferences for this task (idempotency)
            existing_refs: set[str] = set()
            async for ref in TaskReference.objects.filter(task_id=match.task_id).values_list(
                "session_id", "start_time", "end_time"
            ):
                existing_refs.add(f"{ref[0]}:{ref[1]}:{ref[2]}")

            # Filter to only NEW segments (not already linked to this task)
            new_segments = [
                seg
                for seg in cluster_segments
                if f"{seg.session_id}:{seg.start_time}:{seg.end_time}" not in existing_refs
            ]

            if new_segments:
                # Get all distinct_ids from existing refs + new segments for accurate user count
                existing_distinct_ids: list[str] = [
                    ref
                    async for ref in TaskReference.objects.filter(task_id=match.task_id).values_list(
                        "distinct_id", flat=True
                    )
                ]
                all_distinct_ids = existing_distinct_ids + [seg.distinct_id for seg in new_segments]
                relevant_user_count = await sync_to_async(count_distinct_persons)(team, all_distinct_ids)

                task.relevant_user_count = relevant_user_count
                task.occurrence_count += len(new_segments)

                # Find most recent occurrence from new segments
                for segment in new_segments:
                    session_start_time = datetime.fromisoformat(segment.session_start_time.replace("Z", "+00:00"))
                    segment_start_time = session_start_time + timedelta(
                        seconds=_parse_timestamp_to_seconds(segment.start_time)
                    )
                    if task.last_occurrence_at is None or segment_start_time > task.last_occurrence_at:
                        task.last_occurrence_at = segment_start_time

                task.priority_score = calculate_priority_score(
                    relevant_user_count=task.relevant_user_count,
                )

                await task.asave()
                tasks_updated += 1

                logger.info(
                    "Updated task from matched cluster",
                    task_id=str(task.id),
                    cluster_id=match.cluster_id,
                    new_segments=len(new_segments),
                    skipped_existing=len(cluster_segments) - len(new_segments),
                )

        task_ids.append(str(task.id))

    # 3. Create TaskReference records (idempotent - only count truly new links)
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

        session_start_time = datetime.fromisoformat(segment.session_start_time.replace("Z", "+00:00"))
        segment_start_time = session_start_time + timedelta(seconds=_parse_timestamp_to_seconds(segment.start_time))
        segment_end_time = session_start_time + timedelta(seconds=_parse_timestamp_to_seconds(segment.end_time))
        _, created = await TaskReference.objects.aupdate_or_create(
            task=task,
            session_id=segment.session_id,
            start_time=segment_start_time,
            end_time=segment_end_time,
            defaults={
                "team": team,
                "distinct_id": segment.distinct_id,
                "content": segment.content[:1000],
                "distance_to_centroid": None,
            },
        )
        if created:
            links_created += 1

    return PersistTasksResult(
        tasks_created=tasks_created,
        tasks_updated=tasks_updated,
        task_ids=task_ids,
        links_created=links_created,
    )
