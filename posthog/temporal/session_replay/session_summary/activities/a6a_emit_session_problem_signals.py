"""
Activity 6a of the video-based summarization workflow:
Emit signals for consolidated segments that indicate user problems.

Runs after consolidation, emitting problem-indicating segments directly as signals
instead of relying on the batch clustering pipeline.
"""

import structlog
import temporalio

from posthog.models.exported_asset import ExportedAsset
from posthog.models.team.team import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    VideoSummarySingleSessionInputs,
)

from products.signals.backend.api import emit_signal

from ee.hogai.session_summaries.constants import FULL_VIDEO_EXPORT_FORMAT

logger = structlog.get_logger(__name__)


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
