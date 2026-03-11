"""
Activity 6a of the video-based summarization workflow:
Emit signals for consolidated segments that indicate user problems.

Runs after consolidation, emitting problem-indicating segments directly as signals
instead of relying on the batch clustering pipeline.
"""

import structlog
import temporalio

from posthog.models.team.team import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    VideoSummarySingleSessionInputs,
)

logger = structlog.get_logger(__name__)

PROBLEM_TYPE_WEIGHTS: dict[str, float] = {
    "blocking_exception": 0.5,
    "non_blocking_exception": 0.3,
    "abandonment": 0.4,
    "confusion": 0.3,
    "failure": 0.3,
}


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


@temporalio.activity.defn
async def emit_session_problem_signals_activity(
    inputs: VideoSummarySingleSessionInputs,
    analysis: ConsolidatedVideoAnalysis,
) -> int:
    """Emit signals for consolidated segments that indicate user problems.

    Returns the number of signals emitted.
    """
    from products.signals.backend.api import emit_signal

    team = await Team.objects.select_related("organization").aget(id=inputs.team_id)

    if not team.organization.is_ai_data_processing_approved:
        return 0

    session_metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(
        session_id=inputs.session_id,
        team=team,
    )

    signals_emitted = 0

    for segment in analysis.segments:
        problem_type = _classify_problem(segment)
        if problem_type is None:
            continue

        source_id = f"{inputs.session_id}:{segment.start_time}:{segment.end_time}"
        weight = PROBLEM_TYPE_WEIGHTS.get(problem_type, 0.3)

        extra: dict = {
            "session_id": inputs.session_id,
            "segment_title": segment.title,
            "start_time": segment.start_time,
            "end_time": segment.end_time,
            "problem_type": problem_type,
            "distinct_id": inputs.user_distinct_id_to_log or "",
        }
        if session_metadata:
            extra["session_start_time"] = session_metadata["start_time"].isoformat()
            extra["session_end_time"] = session_metadata["end_time"].isoformat()

        try:
            await emit_signal(
                team=team,
                source_product="session_replay",
                source_type="session_problem",
                source_id=source_id,
                description=segment.description,
                weight=weight,
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
