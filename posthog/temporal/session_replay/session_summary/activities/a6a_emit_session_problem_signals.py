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

from ee.hogai.session_summaries.constants import FULL_VIDEO_EXPORT_FORMAT

logger = structlog.get_logger(__name__)

PROBLEM_TYPE_WEIGHTS: dict[str, float] = {
    "blocking_exception": 0.5,
    "non_blocking_exception": 0.3,
    "abandonment": 0.4,
    "confusion": 0.3,
    "failure": 0.3,
}

# Cap event history per segment to keep signal payloads reasonable
MAX_EVENTS_PER_SEGMENT = 50

# Non-user-behavior events to skip in event history — these are internal/system events
# that don't help investigate what the user was doing during a problem segment.
_EVENTS_TO_SKIP_IN_HISTORY = frozenset(
    {
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
        "$pageleave",
        "$set",
        "$web_vitals",
    }
)


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


def _parse_time_to_seconds(time_str: str) -> int:
    """Parse MM:SS or HH:MM:SS format to total seconds."""
    parts = time_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    raise ValueError(f"Invalid time format: {time_str}")


def _format_seconds_as_time(seconds: float) -> str:
    """Format seconds as MM:SS.nnn or HH:MM:SS.nnn."""
    total_seconds = int(seconds)
    millis = int(round((seconds - total_seconds) * 1000))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


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
    for name in ("event", "timestamp", "$current_url", "$event_type", "elements_chain_texts"):
        # Column names may or may not have a $ prefix depending on HogQL aliasing
        for i, col in enumerate(columns):
            if col.replace("$", "") == name.replace("$", ""):
                col_index[name] = i
                break

    if "event" not in col_index or "timestamp" not in col_index:
        return []

    segment_start_abs = session_start_time + datetime.timedelta(seconds=segment_start_seconds)
    segment_end_abs = session_start_time + datetime.timedelta(seconds=segment_end_seconds)

    event_idx = col_index["event"]
    entries: list[dict] = []
    for row in events:
        if row[event_idx] in _EVENTS_TO_SKIP_IN_HISTORY:
            continue
        event_ts = row[col_index["timestamp"]]
        if isinstance(event_ts, str):
            event_ts = datetime.datetime.fromisoformat(event_ts)
        if not isinstance(event_ts, datetime.datetime):
            continue
        # Make comparison timezone-aware if needed
        if event_ts.tzinfo is not None and segment_start_abs.tzinfo is None:
            segment_start_abs = segment_start_abs.replace(tzinfo=event_ts.tzinfo)
            segment_end_abs = segment_end_abs.replace(tzinfo=event_ts.tzinfo)
        if event_ts < segment_start_abs or event_ts > segment_end_abs:
            continue

        offset_seconds = max(0.0, (event_ts - session_start_time).total_seconds())
        entry: dict = {
            "event": row[col_index["event"]],
            "timestamp": _format_seconds_as_time(offset_seconds),
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


def _fetch_session_events(session_id: str, team: Team, metadata: RecordingMetadata) -> tuple[list[str], list] | None:
    """Fetch session events for event history. Returns (columns, events) or None."""
    events_obj = SessionReplayEvents()
    columns, events = events_obj.get_events(
        session_id=session_id,
        team=team,
        metadata=metadata,
        events_to_ignore=["$feature_flag_called"],
    )
    if not columns or not events:
        return None
    return columns, events


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
            session_events_data = await database_sync_to_async(_fetch_session_events)(
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

            # Build abbreviated event history for this segment's time range
            if session_events_data is not None:
                columns, events = session_events_data
                event_history = _build_segment_event_history(
                    events=events,
                    columns=columns,
                    session_start_time=session_metadata["start_time"],
                    segment_start_seconds=_parse_time_to_seconds(segment.start_time),
                    segment_end_seconds=_parse_time_to_seconds(segment.end_time),
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
