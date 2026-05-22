from datetime import timedelta

from django.db import transaction
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
from ee.models.session_summaries import SingleSessionSummary

logger = structlog.get_logger(__name__)

VIDEO_ANALYSIS_PLAYBACK_SPEED = 8
VIDEO_ANALYSIS_RECORDING_FPS = 3  # 3 frames per 1 second of original real time


def _refresh_asset_input_params_locked(asset_id: int, session_id: str) -> None:
    """SELECT FOR UPDATE serializes this with finalize_rasterization's own JSONB write."""
    with transaction.atomic():
        asset = ExportedAsset.objects.select_for_update().get(id=asset_id)
        ctx = dict(asset.export_context or {})
        ctx["session_recording_id"] = session_id
        ctx["playback_speed"] = VIDEO_ANALYSIS_PLAYBACK_SPEED
        ctx["recording_fps"] = VIDEO_ANALYSIS_RECORDING_FPS
        ctx["show_metadata_footer"] = True
        if ctx != asset.export_context:
            asset.export_context = ctx
            asset.save(update_fields=["export_context"])


@temporalio.activity.defn
async def prep_session_video_asset_activity(
    inputs: VideoSummarySingleSessionInputs,
) -> PrepSessionVideoAssetResult | None:
    # Re-check the summary guard before kicking off rasterize/upload/fan-out.
    existing_summary = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
        team_id=inputs.team_id,
        session_id=inputs.session_id,
        extra_summary_context=inputs.extra_summary_context,
    )
    if existing_summary is not None:
        return None
    team = await Team.objects.aget(id=inputs.team_id)
    metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(
        session_id=inputs.session_id,
        team=team,
    )
    if not metadata:
        msg = f"No metadata found for session {inputs.session_id}"
        logger.error(msg, session_id=inputs.session_id, signals_type="session-summaries")
        raise ValueError(msg)
    session_duration = metadata["duration"]

    if session_duration < MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S:
        logger.warning(
            f"Session {inputs.session_id} in team {inputs.team_id} is too short ({session_duration:.2f}s) to summarize, skipping",
            extra={"session_id": inputs.session_id, "team_id": inputs.team_id, "signals_type": "session-summaries"},
        )
        return None

    # TODO: attach Gemini Files API id to the asset with an expiration date so we can reuse it.
    # Scope reuse to summary-owned assets (`is_system=True`) so user-triggered exports of the
    # same recording aren't matched and overwritten by the AI render path.
    existing_asset = await ExportedAsset.objects.filter(
        team_id=inputs.team_id,
        export_format=FULL_VIDEO_EXPORT_FORMAT,
        export_context__session_recording_id=inputs.session_id,
        is_system=True,
    ).afirst()

    if existing_asset:
        # Row-locked refresh so the fingerprint update doesn't race finalize_rasterization.
        await database_sync_to_async(_refresh_asset_input_params_locked, thread_sensitive=False)(
            existing_asset.id, inputs.session_id
        )
        logger.debug(
            f"Reusing existing video export asset {existing_asset.id} for session {inputs.session_id}",
            session_id=inputs.session_id,
            asset_id=existing_asset.id,
            signals_type="session-summaries",
        )
        return PrepSessionVideoAssetResult(
            asset_id=existing_asset.id,
            team_api_token=team.api_token,
            team_name=team.name,
        )

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
        is_system=True,
    )

    logger.debug(
        f"Created ExportedAsset {exported_asset.id} for session {inputs.session_id}",
        session_id=inputs.session_id,
        asset_id=exported_asset.id,
        signals_type="session-summaries",
    )

    return PrepSessionVideoAssetResult(
        asset_id=exported_asset.id,
        team_api_token=team.api_token,
        team_name=team.name,
    )
