import json
from datetime import timedelta

from django.conf import settings

import structlog
import temporalio.workflow as wf
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.session_summary.activities.video_analysis import (
    CHUNK_DURATION,
    analyze_video_segment_activity,
    consolidate_video_segments_activity,
    embed_and_store_segments_activity,
    export_session_video_activity,
    store_video_session_summary_activity,
    upload_video_to_gemini_activity,
)
from posthog.temporal.ai.session_summary.types.video import (
    ConsolidatedVideoSegment,
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect

from ee.hogai.session_summaries.session.summarize_session import ExtraSummaryContext

logger = structlog.get_logger(__name__)


@wf.defn(name="summarize-session-with-video")
class SummarizeSingleSessionWithVideoWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> VideoSummarySingleSessionInputs:
        """Parse inputs from the management command CLI"""
        loaded = json.loads(inputs[0])
        return VideoSummarySingleSessionInputs(**loaded)

    @wf.run
    async def run(self, inputs: VideoSummarySingleSessionInputs) -> list[ConsolidatedVideoSegment]:
        """Execute video-based session segmentation workflow

        Uploads the full video once to Gemini, then analyzes segments in parallel.
        """
        import asyncio

        retry_policy = RetryPolicy(maximum_attempts=3)

        # Activity 1: Export full session video
        asset_id = await wf.execute_activity(
            export_session_video_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=30),  # Video export can take time
            retry_policy=retry_policy,
        )

        # Activity 2: Upload full video to Gemini (single upload)
        uploaded_video = await wf.execute_activity(
            upload_video_to_gemini_activity,
            args=(inputs, asset_id),
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=retry_policy,
        )

        # Calculate segment specs based on video duration
        duration = uploaded_video.duration
        num_segments = int(duration / CHUNK_DURATION) + (1 if duration % CHUNK_DURATION > 0 else 0)
        segment_specs = [
            VideoSegmentSpec(
                segment_index=i,
                start_time=i * CHUNK_DURATION,
                end_time=min((i + 1) * CHUNK_DURATION, duration),
            )
            for i in range(num_segments)
        ]

        # Activity 3: Analyze all segments in parallel
        segment_tasks = [
            wf.execute_activity(
                analyze_video_segment_activity,
                args=(inputs, uploaded_video, segment_spec),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )
            for segment_spec in segment_specs
        ]
        segment_results = await asyncio.gather(*segment_tasks)

        # Flatten results from all segments
        raw_segments: list[VideoSegmentOutput] = []
        for segment_output_list in segment_results:
            raw_segments.extend(segment_output_list)

        if not raw_segments:
            raise ApplicationError(
                f"No segments extracted from video analysis for session {inputs.session_id}. "
                "All video segments may have been static or the LLM output format was not parseable.",
                non_retryable=True,
            )

        # Activity 4: Consolidate raw segments into meaningful semantic segments
        consolidated_segments: list[ConsolidatedVideoSegment] = await wf.execute_activity(
            consolidate_video_segments_activity,
            args=(inputs, raw_segments),
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=retry_policy,
        )

        # Activity 5: Generate embeddings for all segments and store in ClickHouse via Kafka
        await wf.execute_activity(
            embed_and_store_segments_activity,
            args=(inputs, consolidated_segments, asset_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        # Activity 6: Store video-based summary in database
        await wf.execute_activity(
            store_video_session_summary_activity,
            args=(inputs, consolidated_segments),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        return consolidated_segments


async def execute_summarize_session_with_video(
    session_id: str,
    user: User,
    team: Team,
    model_to_use: str = "gemini-2.5-flash",
    extra_summary_context: ExtraSummaryContext | None = None,
) -> list[ConsolidatedVideoSegment]:
    """
    Execute video-based session segmentation workflow.

    This workflow:
    1. Exports the full session recording as a video
    2. Uploads the video once to Gemini
    3. Analyzes 15-second segments in parallel using video_metadata for time ranges
    4. Consolidates raw segments into meaningful semantic segments with titles
    5. Stores consolidated segments as embeddings

    Args:
        session_id: Session recording ID to analyze
        user: User who initiated the analysis
        team: Team context
        model_to_use: Gemini model to use (default: gemini-2.5-flash)
        extra_summary_context: Additional context for analysis

    Returns:
        List of consolidated segments with meaningful titles and detailed descriptions
    """
    # Prepare workflow inputs
    redis_key_base = f"session-video-summary:single:{user.id}-{team.id}:{session_id}"

    session_input = VideoSummarySingleSessionInputs(
        session_id=session_id,
        user_id=user.id,
        user_distinct_id_to_log=user.distinct_id,
        team_id=team.id,
        redis_key_base=redis_key_base,
        model_to_use=model_to_use,
        extra_summary_context=extra_summary_context,
    )

    # Generate unique workflow ID
    import uuid

    workflow_id = f"session-video-summary:single:{session_id}:{user.id}:{uuid.uuid4()}"

    logger.info(
        f"Starting video-based session segmentation workflow for session {session_id}",
        session_id=session_id,
        workflow_id=workflow_id,
    )

    # Execute workflow
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))

    segments = await client.execute_workflow(
        "summarize-session-with-video",
        session_input,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.MAX_AI_TASK_QUEUE,
        retry_policy=retry_policy,
    )

    logger.info(
        f"Video-based session segmentation completed for session {session_id}",
        session_id=session_id,
        segment_count=len(segments),
    )

    return segments
