"""
Activity 1 of the video-based summarization workflow:
Exporting the session as a video.
(Python modules have to start with a letter, hence the file is prefixed `a1_` instead of `1_`.)
"""

import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils.timezone import now

import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.models import Team
from posthog.models.exported_asset import ExportedAsset
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.video import VideoSummarySingleSessionInputs
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs, VideoExportWorkflow

from ee.hogai.session_summaries.constants import EXPIRES_AFTER_DAYS, MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S
from ee.hogai.session_summaries.tracking import capture_session_summary_timing

logger = structlog.get_logger(__name__)

# We can speed things up a bit right now - but not too much, as CSS animations are the same speed
VIDEO_ANALYSIS_PLAYBACK_SPEED = 1


@temporalio.activity.defn
async def export_session_video_activity(inputs: VideoSummarySingleSessionInputs) -> int | None:
    """Export full session video and return ExportedAsset ID, or None if session is too short"""
    start_time = time.monotonic()
    success = False
    try:
        # Check for existing exported asset for this session
        # TODO: Find a way to attach Gemini Files API id to the asset, with an expiration date, so we can reuse it (instead of re-uploading)
        # or remove the video from Files API after processing it (so we don't hit Files API limits)
        existing_asset = (
            await ExportedAsset.objects.filter(
                team_id=inputs.team_id,
                # TODO: Use constant
                export_format="video/mp4",
                export_context__session_recording_id=inputs.session_id,
            )
            .exclude(content_location__isnull=True, content__isnull=True)
            .afirst()
        )

        if existing_asset:
            # Check duration from existing asset's export_context
            existing_duration_s = (
                existing_asset.export_context.get("duration", 0) if existing_asset.export_context else 0
            )
            if existing_duration_s < MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S:
                logger.warning(
                    f"Session {inputs.session_id} in team {inputs.team_id} is too short ({existing_duration_s * 1000:.0f}ms) to summarize, skipping",
                    extra={
                        "session_id": inputs.session_id,
                        "team_id": inputs.team_id,
                        "signals_type": "session-summaries",
                    },
                )
                return None
            logger.debug(
                f"Found existing video export for session {inputs.session_id}, reusing asset {existing_asset.id}",
                session_id=inputs.session_id,
                asset_id=existing_asset.id,
                signals_type="session-summaries",
            )
            return existing_asset.id

        # Get session duration from metadata
        team = await Team.objects.aget(id=inputs.team_id)
        metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(
            session_id=inputs.session_id,
            team=team,
        )
        if not metadata:
            msg = f"No metadata found for session {inputs.session_id}"
            logger.error(msg, session_id=inputs.session_id, signals_type="session-summaries")
            raise ValueError(msg)
        session_duration = metadata["duration"]  # duration is in seconds

        # Check if session is too short for summarization
        if session_duration < MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S:
            logger.warning(
                f"Session {inputs.session_id} in team {inputs.team_id} is too short ({session_duration:.2f}s) to summarize, skipping",
                extra={"session_id": inputs.session_id, "team_id": inputs.team_id, "signals_type": "session-summaries"},
            )
            return None

        # Create ExportedAsset
        filename = f"session-video-summary_{inputs.session_id}_{uuid.uuid4()}"
        created_at = now()
        exported_asset = await ExportedAsset.objects.acreate(
            team_id=inputs.team_id,
            # TODO: Use constant
            export_format="video/mp4",
            export_context={
                "session_recording_id": inputs.session_id,
                "timestamp": 0,  # Start from beginning
                "filename": filename,
                "duration": session_duration,
                "playback_speed": VIDEO_ANALYSIS_PLAYBACK_SPEED,
                "mode": "video",
                "show_metadata_footer": True,
            },
            created_by_id=inputs.user_id,
            created_at=created_at,
            expires_after=created_at + timedelta(days=EXPIRES_AFTER_DAYS),  # Similar to recordings TTL
        )

        # Actually export the video
        client = await async_connect()
        workflow_id = f"session-video-summary-export_{inputs.team_id}_{inputs.session_id}"
        try:
            await client.execute_workflow(
                VideoExportWorkflow.run,
                VideoExportInputs(exported_asset_id=exported_asset.id, use_puppeteer=True),
                id=workflow_id,
                task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                # Keep hard limit to avoid hanging workflows
                execution_timeout=timedelta(hours=3),
            )
        except WorkflowAlreadyStartedError:
            # Another request already started exporting this session - wait for it to complete
            logger.debug(
                f"Video export workflow already running for session {inputs.session_id}, waiting for completion",
                session_id=inputs.session_id,
                workflow_id=workflow_id,
                signals_type="session-summaries",
            )
            handle = client.get_workflow_handle(workflow_id)
            await handle.result()

        logger.debug(
            f"Video exported successfully for session {inputs.session_id}",
            session_id=inputs.session_id,
            asset_id=exported_asset.id,
            signals_type="session-summaries",
        )

        success = True
        return exported_asset.id

    except Exception as e:
        logger.exception(
            f"Failed to export video for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        raise
    finally:
        duration_seconds = time.monotonic() - start_time
        team = await Team.objects.aget(id=inputs.team_id)
        capture_session_summary_timing(
            user_distinct_id=inputs.user_distinct_id_to_log,
            team=team,
            session_id=inputs.session_id,
            timing_type="video_render",
            duration_seconds=duration_seconds,
            success=success,
        )
