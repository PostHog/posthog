from datetime import timedelta

from django.conf import settings
from django.utils.timezone import now

import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models.exported_asset import ExportedAsset
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.video import VideoSummarySingleSessionInputs
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs, VideoExportWorkflow

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_EXPORT_MIME_TYPE, EXPIRES_AFTER_DAYS
from ee.hogai.session_summaries.session.input_data import get_team

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def export_session_video_activity(inputs: VideoSummarySingleSessionInputs) -> int:
    """Export full session video and return ExportedAsset ID"""
    try:
        # Check for existing exported asset for this session
        existing_asset = (
            await ExportedAsset.objects.filter(
                team_id=inputs.team_id,
                export_format=DEFAULT_VIDEO_EXPORT_MIME_TYPE,
                export_context__session_recording_id=inputs.session_id,
            )
            .exclude(content_location__isnull=True, content__isnull=True)
            .afirst()
        )

        if existing_asset:
            logger.info(
                f"Found existing video export for session {inputs.session_id}, reusing asset {existing_asset.id}",
                session_id=inputs.session_id,
                asset_id=existing_asset.id,
            )
            return existing_asset.id

        # Get session duration from metadata
        team = await database_sync_to_async(get_team)(team_id=inputs.team_id)
        metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(
            session_id=inputs.session_id,
            team=team,
        )
        if not metadata:
            raise ValueError(f"No metadata found for session {inputs.session_id}")
        session_duration = metadata["duration"]  # duration is in seconds

        # Create filename for the video
        import uuid

        filename = f"session-video-summary_{inputs.session_id}_{uuid.uuid4()}"

        # Create ExportedAsset
        created_at = now()
        # Keep indefinitely - set expires_after to far future
        exported_asset = await ExportedAsset.objects.acreate(
            team_id=inputs.team_id,
            export_format=DEFAULT_VIDEO_EXPORT_MIME_TYPE,
            export_context={
                "session_recording_id": inputs.session_id,
                "timestamp": 0,  # Start from beginning
                "filename": filename,
                "duration": session_duration,
                "playback_speed": 1.0,  # Normal speed
                "mode": "video",
            },
            created_by_id=inputs.user_id,
            created_at=created_at,
            expires_after=created_at + timedelta(days=EXPIRES_AFTER_DAYS),  # Similar to recordings TTL
        )

        # Execute VideoExportWorkflow
        client = await async_connect()
        await client.execute_workflow(
            VideoExportWorkflow.run,
            VideoExportInputs(exported_asset_id=exported_asset.id),
            id=f"session-video-summary-export_{inputs.session_id}_{uuid.uuid4()}",
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )

        logger.info(
            f"Video exported successfully for session {inputs.session_id}",
            session_id=inputs.session_id,
            asset_id=exported_asset.id,
        )

        return exported_asset.id

    except Exception as e:
        logger.exception(
            f"Failed to export video for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
        )
        raise
