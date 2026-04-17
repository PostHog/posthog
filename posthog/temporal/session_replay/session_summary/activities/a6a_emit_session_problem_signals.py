"""
Activity 6a of the video-based summarization workflow:
Emit signals for consolidated segments that indicate user problems.

Runs after consolidation, emitting problem-indicating segments directly as signals
instead of relying on the batch clustering pipeline.
"""

import datetime

import structlog
import temporalio

from posthog.models.exported_asset import ExportedAsset
from posthog.models.team.team import Team
from posthog.session_recordings.models.metadata import RecordingMetadata
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.types.video import (
    ConsolidatedVideoAnalysis,
    ConsolidatedVideoSegment,
    VideoSummarySingleSessionInputs,
)
from posthog.temporal.session_replay.session_summary.utils import format_seconds_as_mm_ss, parse_str_timestamp_to_s

from products.signals.backend.api import emit_signal

from ee.hogai.session_summaries.constants import FULL_VIDEO_EXPORT_FORMAT

logger = structlog.get_logger(__name__)

# Cap event history per segment to keep signal payloads reasonable
MAX_EVENTS_PER_SEGMENT = 50

# Non-user-behavior events to skip in event history — these are internal PostHog events that don't help investigate
# what the user was doing during a problem segment.
_EVENTS_TO_SKIP_IN_HISTORY = [
    "$$heatmap",
    "$capture_metrics",
    "$copy_autocapture",
    "$create_alias",
    "$feature_enrollment_update",
    "$feature_flag_called",
    "$feature_interaction",
    "$feature_view",
    "$groupidentify",
    "$identify",
    "$merge_dangerously",
    "$opt_in",
    "$set",
    "$web_vitals",
]


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

    # Fetch session events once for building event history across all segments
    session_events_data: tuple[list[str], list] | None = None
    if session_metadata:
        try:
            session_events_data = await _fetch_session_events(
                session_id=inputs.session_id,
                team=team,
                metadata=session_metadata,
            )
        except Exception:
            logger.warning(
                "Failed to fetch session events for event history",
                session_id=inputs.session_id,
                signals_type="session-summaries",
                exc_info=True,
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

            # Build abbreviated event history for this segment's time range
            if session_events_data is not None:
                columns, events = session_events_data
                event_history = _build_segment_event_history(
                    events=events,
                    columns=columns,
                    session_start_time=session_metadata["start_time"],
                    segment_start_seconds=parse_str_timestamp_to_s(segment.start_time),
                    segment_end_seconds=parse_str_timestamp_to_s(segment.end_time),
                )
                if event_history:
                    extra["event_history"] = event_history

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


def _build_segment_event_history(
    events: list,
    columns: list[str],
    session_start_time: datetime.datetime,
    segment_start_seconds: int,
    segment_end_seconds: int,
) -> list[dict]:
    """Build abbreviated event history for a segment's time range.

    Returns a list of dicts matching SessionProblemEventEntry schema fields.
    """
    col_index: dict[str, int] = {}
    for i, col in enumerate(columns):
        col_index[col] = i

    if "event" not in col_index or "timestamp" not in col_index:
        return []

    segment_start_abs = session_start_time + datetime.timedelta(seconds=segment_start_seconds)
    segment_end_abs = session_start_time + datetime.timedelta(seconds=segment_end_seconds)

    entries: list[dict] = []
    for row in events:

        event_ts = row[col_index["timestamp"]]
        if isinstance(event_ts, str):
            try:
                event_ts = datetime.datetime.fromisoformat(event_ts)
            except (ValueError, TypeError):
                continue
        if not isinstance(event_ts, datetime.datetime):
            continue

        if event_ts < segment_start_abs or event_ts > segment_end_abs:
            continue

        offset_seconds = max(0.0, (event_ts - session_start_time).total_seconds())
        entry: dict = {
            "event": row[col_index["event"]],
            "timestamp": format_seconds_as_mm_ss(offset_seconds, include_ms=True),
        }
        if "$current_url" in col_index:
            url = row[col_index["$current_url"]]
            if url:
                entry["current_url"] = url
        if "$event_type" in col_index:
            event_type = row[col_index["$event_type"]]
            if event_type:
                entry["event_type"] = event_type
        if "elements_chain_texts" in col_index:
            texts = row[col_index["elements_chain_texts"]]
            if texts and isinstance(texts, list):
                joined = " > ".join(t for t in texts if t)
                if joined:
                    entry["interaction_text"] = joined

        entries.append(entry)
        if len(entries) >= MAX_EVENTS_PER_SEGMENT:
            break

    return entries


@database_sync_to_async
def _fetch_session_events(session_id: str, team: Team, metadata: RecordingMetadata) -> tuple[list[str], list] | None:
    """Fetch session events for event history. Returns (columns, events) or None."""
    events_obj = SessionReplayEvents()
    columns, events = events_obj.get_events(
        session_id=session_id,
        team=team,
        metadata=metadata,
        events_to_ignore=_EVENTS_TO_SKIP_IN_HISTORY,
    )
    if not columns or not events:
        return None
    return columns, events
