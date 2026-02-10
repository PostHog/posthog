"""
Activity 1 of the video-based summarization workflow:
Preparing the session video export (creating/finding an ExportedAsset record).
The actual video rendering is executed as a child workflow by the parent summarization workflow.
(Python modules have to start with a letter, hence the file is prefixed `a1_` instead of `1_`.)
"""

import time
import uuid
from datetime import timedelta

from django.utils.timezone import now

import structlog
import temporalio

from posthog.models import Team
from posthog.models.exported_asset import ExportedAsset
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.video import PrepSessionVideoAssetResult, VideoSummarySingleSessionInputs

from ee.hogai.session_summaries.constants import (
    EXPIRES_AFTER_DAYS,
    FULL_VIDEO_EXPORT_FORMAT,
    MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S,
)
from ee.hogai.session_summaries.tracking import capture_session_summary_timing

logger = structlog.get_logger(__name__)

# We can speed things up a bit right now - but not too much, as CSS animations are the same speed
VIDEO_ANALYSIS_PLAYBACK_SPEED = 1


@temporalio.activity.defn
async def prep_session_video_asset_activity(
    inputs: VideoSummarySingleSessionInputs,
) -> PrepSessionVideoAssetResult | None:
    """Prepare session video export: find or create ExportedAsset record."""
    start_time = time.monotonic()
    success = False
    try:
        # Check for existing exported asset for this session
        # TODO: Find a way to attach Gemini Files API id to the asset, with an expiration date, so we can reuse it (instead of re-uploading)
        # or remove the video from Files API after processing it (so we don't hit Files API limits)
        existing_asset = (
            await ExportedAsset.objects.filter(
                team_id=inputs.team_id,
                export_format=FULL_VIDEO_EXPORT_FORMAT,
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
            success = True
            return PrepSessionVideoAssetResult(asset_id=existing_asset.id, needs_export=False)

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

        # Create ExportedAsset record (the actual video rendering happens as a child workflow)
        filename = f"session-video-summary_{inputs.session_id}_{uuid.uuid4()}"
        created_at = now()
        exported_asset = await ExportedAsset.objects.acreate(
            team_id=inputs.team_id,
            export_format=FULL_VIDEO_EXPORT_FORMAT,
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

        logger.debug(
            f"Created ExportedAsset {exported_asset.id} for session {inputs.session_id}, needs video rendering",
            session_id=inputs.session_id,
            asset_id=exported_asset.id,
            signals_type="session-summaries",
        )

        success = True
        return PrepSessionVideoAssetResult(asset_id=exported_asset.id, needs_export=True)

    except Exception as e:
        logger.exception(
            f"Failed to prepare video export for session {inputs.session_id}: {e}",
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
