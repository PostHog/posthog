"""
Activity 6a of the video-based summarization workflow:
Emit signals for consolidated segments that indicate user problems.

Runs after consolidation, emitting problem-indicating segments directly as signals
instead of relying on the batch clustering pipeline.

Also rasterizes a short GIF preview of each problematic moment (minimum 30s)
for quick inline display in the desktop app.
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.utils.timezone import now

import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models.exported_asset import ExportedAsset
from posthog.models.team.team import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.session_replay.rasterize_recording.types import RasterizeRecordingInputs
from posthog.temporal.session_replay.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    VideoSummarySingleSessionInputs,
)

from products.signals.backend.api import emit_signal

from ee.hogai.session_summaries.constants import FULL_VIDEO_EXPORT_FORMAT

logger = structlog.get_logger(__name__)

# Minimum duration for the moment preview GIF (seconds)
MIN_MOMENT_PREVIEW_DURATION_S = 30
# Preview GIF export format
MOMENT_PREVIEW_EXPORT_FORMAT = "image/gif"
# How long to keep moment preview GIFs
MOMENT_PREVIEW_EXPIRES_DAYS = 90


def _parse_timestamp_to_seconds(ts: str) -> float:
    """Parse MM:SS or HH:MM:SS timestamp to seconds."""
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    elif len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return 0.0


async def _rasterize_moment_preview(
    team_id: int,
    session_id: str,
    start_time_s: float,
    end_time_s: float,
) -> int | None:
    """Create a GIF preview of a session moment and return the ExportedAsset ID.

    Expands the clip to at least MIN_MOMENT_PREVIEW_DURATION_S seconds where possible,
    clamping start to 0 and compensating the end when near the recording start.
    Returns None if rasterization fails.
    """
    duration = end_time_s - start_time_s
    if duration < MIN_MOMENT_PREVIEW_DURATION_S:
        # Expand symmetrically around the midpoint to reach the minimum
        midpoint = (start_time_s + end_time_s) / 2
        half = MIN_MOMENT_PREVIEW_DURATION_S / 2
        start_time_s = max(0, midpoint - half)
        end_time_s = midpoint + half
        # When start was clamped to 0, extend end to compensate
        if start_time_s == 0:
            end_time_s = MIN_MOMENT_PREVIEW_DURATION_S

    created_at = now()
    expires_after = created_at + timedelta(days=MOMENT_PREVIEW_EXPIRES_DAYS)

    exported_asset = await ExportedAsset.objects.acreate(
        team_id=team_id,
        export_format=MOMENT_PREVIEW_EXPORT_FORMAT,
        export_context={
            "session_recording_id": session_id,
            "start_offset_s": start_time_s,
            "end_offset_s": end_time_s,
            "playback_speed": 1,
            "show_metadata_footer": True,
        },
        created_at=created_at,
        expires_after=expires_after,
    )

    try:
        client = await async_connect()
        await client.execute_workflow(
            "rasterize-recording",
            RasterizeRecordingInputs(exported_asset_id=exported_asset.id),
            id=f"signal-moment-preview_{session_id}_{exported_asset.id}_{uuid.uuid4()}",
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            execution_timeout=timedelta(minutes=10),
        )
        return exported_asset.id
    except Exception:
        logger.exception(
            "Failed to rasterize moment preview",
            session_id=session_id,
            asset_id=exported_asset.id,
            signals_type="session-summaries",
        )
        # Clean up the orphaned asset
        await ExportedAsset.objects.filter(id=exported_asset.id).adelete()
        return None


@temporalio.activity.defn
async def emit_session_problem_signals_activity(
    inputs: VideoSummarySingleSessionInputs,
    analysis: ConsolidatedVideoAnalysis,
) -> int:
    """Emit signals for consolidated segments that indicate user problems.

    Returns the number of signals emitted.
    """

    team = await Team.objects.select_related("organization").aget(id=inputs.team_id)

    if not team.organization.is_ai_data_processing_approved:
        return 0

    session_metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(
        session_id=inputs.session_id,
        team=team,
    )

    # Find the rasterized video export for this session (created by Activity 1)
    exported_asset = await (
        ExportedAsset.objects.filter(
            team_id=inputs.team_id,
            export_format=FULL_VIDEO_EXPORT_FORMAT,
            export_context__session_recording_id=inputs.session_id,
        )
        .exclude(content_location__isnull=True, content__isnull=True)
        .only("id")
        .afirst()
    )

    signals_emitted = 0

    for segment in analysis.segments:
        problem_type = _classify_problem(segment)
        if problem_type is None:
            continue

        source_id = f"{inputs.session_id}:{segment.start_time}:{segment.end_time}"

        # Rasterize a GIF preview of the problematic moment
        start_s = _parse_timestamp_to_seconds(segment.start_time)
        end_s = _parse_timestamp_to_seconds(segment.end_time)
        moment_preview_asset_id = await _rasterize_moment_preview(
            team_id=inputs.team_id,
            session_id=inputs.session_id,
            start_time_s=start_s,
            end_time_s=end_s,
        )

        extra: dict = {
            "session_id": inputs.session_id,
            "segment_title": segment.title,
            "start_time": segment.start_time,
            "end_time": segment.end_time,
            "problem_type": problem_type,
            "distinct_id": session_metadata["distinct_id"] if session_metadata else "",
        }
        if session_metadata:
            extra["session_start_time"] = session_metadata["start_time"].isoformat()
            extra["session_end_time"] = session_metadata["end_time"].isoformat()
            extra["session_duration"] = session_metadata["duration"]
            extra["session_active_seconds"] = session_metadata["active_seconds"]

        if exported_asset is not None:
            extra["exported_asset_id"] = exported_asset.id

        if moment_preview_asset_id is not None:
            extra["moment_preview_asset_id"] = moment_preview_asset_id

        try:
            await emit_signal(
                team=team,
                source_product="session_replay",
                source_type="session_problem",
                source_id=source_id,
                description=segment.description,
                weight=1.0,  # Always research
                extra=extra,
            )
            signals_emitted += 1
            logger.debug(
                f"Emitted session problem signal for {source_id}",
                session_id=inputs.session_id,
                problem_type=problem_type,
                moment_preview_asset_id=moment_preview_asset_id,
                signals_type="session-summaries",
            )
        except Exception:
            logger.exception(
                f"Failed to emit session problem signal for {source_id}",
                session_id=inputs.session_id,
                signals_type="session-summaries",
            )

    if signals_emitted > 0:
        logger.info(
            f"Emitted {signals_emitted} session problem signals for session {inputs.session_id}",
            session_id=inputs.session_id,
            signal_count=signals_emitted,
            signals_type="session-summaries",
        )

    return signals_emitted


def _classify_problem(segment: ConsolidatedVideoSegment) -> str | None:
    """Return the most severe problem type for a segment, or None if no problem detected."""
    if segment.exception == "blocking":
        return "blocking_exception"
    if segment.abandonment_detected:
        return "abandonment"
    if segment.exception == "non-blocking":
        return "non_blocking_exception"
    if segment.confusion_detected:
        return "confusion"
    if not segment.success:
        return "failure"
    return None
