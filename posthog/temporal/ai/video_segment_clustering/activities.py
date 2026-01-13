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

from django.conf import settings
from django.utils import timezone as django_timezone

import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import SummarizeSingleSessionWorkflow
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.clustering import (
    match_clusters_to_existing_tasks,
    perform_hdbscan_clustering,
)
from posthog.temporal.ai.video_segment_clustering.data import (
    fetch_embeddings_by_document_ids,
    fetch_existing_task_centroids,
    fetch_recent_session_ids,
    fetch_video_segments,
)
from posthog.temporal.ai.video_segment_clustering.labeling import generate_cluster_labels_llm
from posthog.temporal.ai.video_segment_clustering.models import (
    Cluster,
    ClusterContext,
    ClusteringResult,
    ClusterLabel,
    ClusterSegmentsActivityInputs,
    CreateNoiseClustersActivityInputs,
    CreateUpdateTasksActivityInputs,
    FetchRecentSessionsActivityInputs,
    FetchRecentSessionsResult,
    FetchSegmentsActivityInputs,
    FetchSegmentsResult,
    GenerateLabelsActivityInputs,
    LabelingResult,
    LinkingResult,
    LinkSegmentsActivityInputs,
    MatchClustersActivityInputs,
    MatchingResult,
    SummarizeSessionsActivityInputs,
    SummarizeSessionsResult,
    TaskCreationResult,
    VideoSegmentMetadata,
)
from posthog.temporal.ai.video_segment_clustering.priority import calculate_priority_score, calculate_task_metrics
from posthog.temporal.common.client import async_connect

from products.tasks.backend.models import Task, TaskSegmentLink, VideoSegmentClusteringState

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL
from ee.models.session_summaries import SingleSessionSummary

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
def _cluster_segments(inputs: ClusterSegmentsActivityInputs) -> ClusteringResult:
    """Fetch embeddings from DB and run HDBSCAN clustering."""
    team = Team.objects.get(id=inputs.team_id)

    # Fetch embeddings directly from ClickHouse (not passed through Temporal due to their total size)
    segments = fetch_embeddings_by_document_ids(team, inputs.document_ids)

    return perform_hdbscan_clustering(segments)


@activity.defn
async def cluster_segments_activity(inputs: ClusterSegmentsActivityInputs) -> ClusteringResult:
    """Activity 2: Cluster video segments using HDBSCAN.

    Fetches embeddings from ClickHouse, then applies PCA dimensionality reduction
    and HDBSCAN clustering. Returns clusters with centroids computed from original embeddings.
    """
    return await asyncio.to_thread(_cluster_segments, inputs)


# Activity 2b: Create single-segment clusters for noise segments
def _create_noise_clusters(inputs: CreateNoiseClustersActivityInputs) -> list[Cluster]:
    """Create single-segment clusters for noise segments."""
    team = Team.objects.get(id=inputs.team_id)

    # Fetch embeddings for these specific documents
    segments = fetch_embeddings_by_document_ids(team, inputs.document_ids)
    segment_lookup = {s.document_id: s for s in segments}

    clusters: list[Cluster] = []
    for i, doc_id in enumerate(inputs.document_ids):
        segment = segment_lookup.get(doc_id)
        if not segment:
            continue

        cluster = Cluster(
            cluster_id=inputs.starting_cluster_id + i,
            segment_ids=[doc_id],
            centroid=segment.embedding,
            size=1,
        )
        clusters.append(cluster)

    return clusters


@activity.defn
async def create_noise_clusters_activity(inputs: CreateNoiseClustersActivityInputs) -> list[Cluster]:
    """Activity 2b: Create single-segment clusters for noise segments.

    For noise segments that didn't cluster with others,
    create individual clusters so they become Tasks.
    """
    return await asyncio.to_thread(_create_noise_clusters, inputs)


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


def _calculate_metrics_from_segments(segments: list[VideoSegmentMetadata]) -> dict:
    """Calculate aggregate metrics from segment metadata."""
    if not segments:
        return {
            "distinct_user_count": 0,
            "occurrence_count": 0,
            "last_occurrence_at": None,
        }

    # Count unique users
    distinct_ids = {s.distinct_id for s in segments}
    distinct_user_count = len(distinct_ids)

    # Find most recent occurrence
    timestamps = []
    for s in segments:
        if s.timestamp:
            try:
                ts = datetime.fromisoformat(s.timestamp.replace("Z", "+00:00"))
                timestamps.append(ts)
            except ValueError:
                pass

    last_occurrence_at = max(timestamps) if timestamps else None

    return {
        "distinct_user_count": distinct_user_count,
        "occurrence_count": len(segments),
        "last_occurrence_at": last_occurrence_at,
    }


# Activity 4: Generate labels
async def _generate_labels(inputs: GenerateLabelsActivityInputs) -> LabelingResult:
    """Generate LLM labels for clusters with actionability filtering."""
    # Build segment lookup
    segment_lookup = {s.document_id: s for s in inputs.segments}

    async def generate_label_for_cluster(cluster):
        """Generate label for a single cluster."""
        # Get segments for this cluster
        cluster_segments = [segment_lookup[sid] for sid in cluster.segment_ids if sid in segment_lookup]

        if not cluster_segments:
            # No segments = not actionable
            return cluster.cluster_id, ClusterLabel(
                actionable=False,
                title="",
                description="",
            )

        # Calculate metrics for this cluster
        metrics = _calculate_metrics_from_segments(cluster_segments)

        # Build context for LLM
        sample_segments = cluster_segments[: constants.DEFAULT_SEGMENTS_PER_CLUSTER_FOR_LABELING]

        context = ClusterContext(
            segment_contents=[s.content for s in sample_segments],
            distinct_user_count=metrics["distinct_user_count"],
            occurrence_count=metrics["occurrence_count"],
            last_occurrence_iso=metrics["last_occurrence_at"].isoformat() if metrics["last_occurrence_at"] else None,
        )

        # Generate label with actionability check
        try:
            label = await generate_cluster_labels_llm(
                team_id=inputs.team_id,
                context=context,
            )
            return cluster.cluster_id, label
        except Exception as e:
            logger.warning(
                "Failed to generate LLM label for cluster, marking not actionable",
                cluster_id=cluster.cluster_id,
                error=str(e),
            )
            return cluster.cluster_id, ClusterLabel(
                actionable=False,
                title="",
                description="",
            )

    # Generate labels in parallel for all clusters
    results = await asyncio.gather(*[generate_label_for_cluster(cluster) for cluster in inputs.clusters])
    labels = dict(results)

    return LabelingResult(labels=labels)


@activity.defn
async def generate_labels_activity(inputs: GenerateLabelsActivityInputs) -> LabelingResult:
    """Activity 4: Generate LLM-based labels for new clusters, i.e. actionable task titles and descriptions."""
    return await _generate_labels(inputs)


# Activity 5: Create/update tasks
def _create_update_tasks(inputs: CreateUpdateTasksActivityInputs) -> TaskCreationResult:
    """Create new Tasks and update existing ones."""
    team = Team.objects.get(id=inputs.team_id)

    # Build segment lookup by document_id
    segment_lookup = {s.document_id: s for s in inputs.segments}

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

        # Calculate priority (based on user count only)
        priority = calculate_priority_score(
            distinct_user_count=metrics["distinct_user_count"],
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

        # Note: We skip centroid updates here because embeddings are no longer passed
        # through Temporal (they're too large). The existing centroid remains valid
        # as it was computed from the initial batch of segments.

        # Recalculate metrics including new segments
        new_metrics = calculate_task_metrics(cluster_segments)

        # Update counts (additive)
        task.distinct_user_count += new_metrics["distinct_user_count"]  # May overcount
        task.occurrence_count += new_metrics["occurrence_count"]

        # Update last occurrence
        if new_metrics["last_occurrence_at"]:
            if task.last_occurrence_at is None or new_metrics["last_occurrence_at"] > task.last_occurrence_at:
                task.last_occurrence_at = new_metrics["last_occurrence_at"]

        # Recalculate priority (based on user count only)
        task.priority_score = calculate_priority_score(
            distinct_user_count=task.distinct_user_count,
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
    team = Team.objects.get(id=inputs.team_id)

    links_created = 0

    for segment in inputs.segments:
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

        # Note: distance_to_centroid is skipped because embeddings are no longer
        # passed through Temporal (they're too large). This is an optional metric.
        distance = None

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
                    "segments_processed": len(inputs.segments),
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


# Session priming activities (run summarization before clustering)


def _fetch_recent_sessions(inputs: FetchRecentSessionsActivityInputs) -> FetchRecentSessionsResult:
    """Fetch sessions that ended recently and may need summarization."""
    team = Team.objects.get(id=inputs.team_id)

    session_ids = fetch_recent_session_ids(
        team=team,
        lookback_hours=inputs.lookback_hours,
    )

    return FetchRecentSessionsResult(session_ids=session_ids)


@activity.defn
async def fetch_recent_sessions_activity(inputs: FetchRecentSessionsActivityInputs) -> FetchRecentSessionsResult:
    """Fetch session IDs that ended within the lookback period.

    These sessions may need summarization to populate the document_embeddings table
    before clustering can find them.
    """
    return await asyncio.to_thread(_fetch_recent_sessions, inputs)


async def _summarize_sessions(inputs: SummarizeSessionsActivityInputs) -> SummarizeSessionsResult:
    """Run session summarization workflows for the given sessions in parallel."""
    team = await Team.objects.aget(id=inputs.team_id)

    # Get system user or first superuser for running summarization
    system_user = await User.objects.filter(is_active=True, is_staff=True).afirst()
    if not system_user:
        system_user = await User.objects.filter(is_active=True).afirst()

    if not system_user:
        logger.warning("No user found to run summarization", team_id=inputs.team_id)
        return SummarizeSessionsResult(
            sessions_summarized=0, sessions_failed=0, sessions_skipped=len(inputs.session_ids)
        )

    # Check which sessions already have summaries (no extra_summary_context for clustering)
    existing_summaries = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=inputs.session_ids,
        extra_summary_context=None,
    )

    client = await async_connect()

    sessions_summarized = 0
    sessions_failed = 0
    sessions_skipped = 0

    # Start workflows only for sessions that don't already have summaries
    handles = []
    for session_id in inputs.session_ids:
        # Skip if summary already exists
        if existing_summaries.get(session_id):
            sessions_skipped += 1
            logger.info("Session summary already exists, skipping", session_id=session_id)
            continue

        try:
            redis_key_base = f"session-summary:clustering:{team.id}:{session_id}"
            workflow_input = SingleSessionSummaryInputs(
                session_id=session_id,
                user_id=system_user.id,
                user_distinct_id_to_log=system_user.distinct_id,
                team_id=team.id,
                redis_key_base=redis_key_base,
                model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
                video_validation_enabled="full",  # Full video-based summarization to populate embeddings
            )

            handle = await client.start_workflow(
                SummarizeSingleSessionWorkflow.run,
                workflow_input,
                id=f"session-summary-clustering-{team.id}-{session_id}",
                task_queue=settings.MAX_AI_TASK_QUEUE,
                execution_timeout=constants.SUMMARIZE_SESSIONS_ACTIVITY_TIMEOUT,
            )
            handles.append((session_id, handle))
        except Exception as e:
            # Workflow may already be running or completed
            if "already started" in str(e).lower() or "already exists" in str(e).lower():
                sessions_skipped += 1
                logger.info("Session summarization already running", session_id=session_id)
            else:
                sessions_failed += 1
                logger.warning("Failed to start summarization workflow", session_id=session_id, error=str(e))

    # Wait for all workflows to complete
    for session_id, handle in handles:
        try:
            await handle.result()
            sessions_summarized += 1
            logger.info("Session summarization completed", session_id=session_id)
        except Exception as e:
            if "already started" in str(e).lower():
                sessions_skipped += 1
            else:
                sessions_failed += 1
                logger.warning("Session summarization failed", session_id=session_id, error=str(e))

    return SummarizeSessionsResult(
        sessions_summarized=sessions_summarized,
        sessions_failed=sessions_failed,
        sessions_skipped=sessions_skipped,
    )


@activity.defn
async def summarize_sessions_activity(inputs: SummarizeSessionsActivityInputs) -> SummarizeSessionsResult:
    """Run video-based session summarization for recent sessions.

    This primes the document_embeddings table with video segments
    so they can be clustered by the main workflow.
    """
    return await _summarize_sessions(inputs)
