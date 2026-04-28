"""
Activity 1 of the video-based summarization workflow:
Preparing the session video export (creating/finding an ExportedAsset record).
The actual video rendering is executed as a child workflow by the parent summarization workflow.
(Python modules have to start with a letter, hence the file is prefixed `a1_` instead of `1_`.)
"""

import time
from datetime import timedelta

from django.utils.timezone import now

import structlog
import temporalio

from posthog.models import Team
from posthog.models.exported_asset import ExportedAsset
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.types.video import (
    PrepSessionVideoAssetResult,
    VideoSummarySingleSessionInputs,
)

from ee.hogai.session_summaries.constants import (
    EXPIRES_AFTER_DAYS,
    FULL_VIDEO_EXPORT_FORMAT,
    MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S,
)
from ee.hogai.session_summaries.tracking import capture_session_summary_timing
from ee.models.session_summaries import SingleSessionSummary

logger = structlog.get_logger(__name__)

VIDEO_ANALYSIS_PLAYBACK_SPEED = 8
VIDEO_ANALYSIS_RECORDING_FPS = 3  # 3 frames per 1 second of original real time


@temporalio.activity.defn
async def prep_session_video_asset_activity(
    inputs: VideoSummarySingleSessionInputs,
) -> PrepSessionVideoAssetResult | None:
    """Prepare session video export: find or create ExportedAsset record."""
    start_time = time.monotonic()
    success = False
    team: Team | None = None
    try:
        # Check if a video-based summary already exists for this session
        existing_summary = await database_sync_to_async(
            SingleSessionSummary.objects.get_summary, thread_sensitive=False
        )(
            team_id=inputs.team_id,
            session_id=inputs.session_id,
            extra_summary_context=inputs.extra_summary_context,
        )
        if existing_summary is not None:
            logger.debug(
                f"Summary already exists for session {inputs.session_id}, skipping video processing",
                session_id=inputs.session_id,
                signals_type="session-summaries",
            )
            success = True
            return None
        # Get session duration from metadata and check minimum threshold
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

        if session_duration < MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S:
            logger.warning(
                f"Session {inputs.session_id} in team {inputs.team_id} is too short ({session_duration:.2f}s) to summarize, skipping",
                extra={"session_id": inputs.session_id, "team_id": inputs.team_id, "signals_type": "session-summaries"},
            )
            return None

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
            logger.debug(
                f"Found existing video export for session {inputs.session_id}, reusing asset {existing_asset.id}",
                session_id=inputs.session_id,
                asset_id=existing_asset.id,
                signals_type="session-summaries",
            )
            success = True
            return PrepSessionVideoAssetResult(
                asset_id=existing_asset.id, needs_export=False, team_api_token=team.api_token
            )

        # Create ExportedAsset record (the actual video rendering happens as a child workflow)
        created_at = now()
        exported_asset = await ExportedAsset.objects.acreate(
            team_id=inputs.team_id,
            export_format=FULL_VIDEO_EXPORT_FORMAT,
            export_context={
                "session_recording_id": inputs.session_id,
                "playback_speed": VIDEO_ANALYSIS_PLAYBACK_SPEED,
                "recording_fps": VIDEO_ANALYSIS_RECORDING_FPS,
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
        return PrepSessionVideoAssetResult(asset_id=exported_asset.id, needs_export=True, team_api_token=team.api_token)

    except Exception as e:
        logger.exception(
            f"Failed to prepare video export for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        raise
    finally:
        duration_seconds = time.monotonic() - start_time
        if team is None:
            team = await Team.objects.aget(id=inputs.team_id)
        capture_session_summary_timing(
            user_distinct_id=inputs.user_distinct_id_to_log,
            team=team,
            session_id=inputs.session_id,
            timing_type="video_render",
            duration_seconds=duration_seconds,
            success=success,
        )
