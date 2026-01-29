"""
Activity 6 of the video-based summarization workflow:
Saving the single session summary.
(Python modules have to start with a letter, hence the file is prefixed `a6_` instead of `6_`.)
"""

from typing import Any

import structlog
import temporalio

from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.ai.session_summary.types.video import ConsolidatedVideoAnalysis, VideoSummarySingleSessionInputs

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import (
    calculate_time_since_start,
    get_column_index,
    prepare_datetime,
    unpack_full_event_id,
)

from .a3_analyze_video_segment import _find_events_in_time_range

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def store_video_session_summary_activity(
    inputs: VideoSummarySingleSessionInputs,
    analysis: ConsolidatedVideoAnalysis,
) -> None:
    """Convert video segments to session summary format and store in database

    This activity:
    1. Retrieves cached event data from Redis (populated by fetch_session_data_activity)
    2. Maps video segments to real events using timestamps
    3. Converts video segments into SessionSummarySerializer format with real event IDs
    4. Stores the summary in SingleSessionSummary table
    5. Marks it with visual_confirmation=True
    """
    try:
        from dateutil import parser as dateutil_parser

        from posthog.models.user import User

        from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
        from ee.models.session_summaries import SessionSummaryRunMeta, SingleSessionSummary

        # Check if summary already exists
        summary_exists = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
            team_id=inputs.team_id,
            session_ids=[inputs.session_id],
            extra_summary_context=inputs.extra_summary_context,
        )

        if summary_exists.get(inputs.session_id):
            logger.debug(
                f"Video-based summary already exists for session {inputs.session_id}, skipping storage",
                session_id=inputs.session_id,
                signals_type="session-summaries",
            )
            return

        # Retrieve cached event data from Redis (populated by fetch_session_data_activity)
        redis_client, redis_input_key, _ = get_redis_state_client(
            key_base=inputs.redis_key_base,
            input_label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=inputs.session_id,
        )
        llm_input = await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            target_class=SingleSessionSummaryLlmInputs,
        )

        # Convert video segments to session summary format, using real events if available
        if llm_input is None:
            msg = f"No LLM input found in Redis for session {inputs.session_id} when storing video-based summary"
            logger.error(msg, session_id=inputs.session_id, signals_type="session-summaries")
            raise ValueError(msg)

        summary_dict = _convert_video_segments_to_session_summary(
            analysis=analysis,
            session_id=inputs.session_id,
            llm_input=llm_input,
        )

        # Validate the summary
        session_summary = SessionSummarySerializer(data=summary_dict)
        if not session_summary.is_valid():
            msg = f"Failed to validate video-based summary for session {inputs.session_id}: {session_summary.errors}"
            logger.error(msg, session_id=inputs.session_id, signals_type="session-summaries")
            raise ValueError(msg)

        # Get session metadata from cached LLM input if available, otherwise leave as None
        if llm_input:
            session_start_time = dateutil_parser.isoparse(llm_input.session_start_time_str)
            session_duration = llm_input.session_duration
            distinct_id = llm_input.distinct_id
        else:
            session_start_time = None
            session_duration = None
            distinct_id = None

        # Get user
        user = await User.objects.aget(id=inputs.user_id)

        # Store the summary in the database
        await database_sync_to_async(SingleSessionSummary.objects.add_summary, thread_sensitive=False)(
            session_id=inputs.session_id,
            team_id=inputs.team_id,
            summary=session_summary,
            exception_event_ids=[],  # Video analysis doesn't identify specific exception events
            extra_summary_context=inputs.extra_summary_context,
            run_metadata=SessionSummaryRunMeta(
                model_used=inputs.model_to_use,
                visual_confirmation=True,  # Mark as video-based
            ),
            session_start_time=session_start_time,
            session_duration=session_duration,
            distinct_id=distinct_id,
            created_by=user,
        )
        logger.debug(
            f"Successfully stored video-based summary for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_count=len(analysis.segments),
            has_real_events=llm_input is not None,
            signals_type="session-summaries",
        )
    except Exception as e:
        logger.exception(
            f"Failed to store video-based summary for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        raise


def _convert_video_segments_to_session_summary(
    analysis: ConsolidatedVideoAnalysis,
    session_id: str,
    llm_input: SingleSessionSummaryLlmInputs,
) -> dict:
    """Maps video segments to real events."""
    segments = analysis.segments
    # Extract data from cached LLM input
    simplified_events_mapping = llm_input.simplified_events_mapping
    event_ids_mapping = llm_input.event_ids_mapping
    simplified_events_columns = llm_input.simplified_events_columns
    url_mapping_reversed = llm_input.url_mapping_reversed
    window_mapping_reversed = llm_input.window_mapping_reversed
    session_start_time_str = llm_input.session_start_time_str
    session_duration = llm_input.session_duration

    # Get column indices for event enrichment
    timestamp_index = get_column_index(simplified_events_columns, "timestamp")
    event_index_index = get_column_index(simplified_events_columns, "event_index")
    event_name_index = get_column_index(simplified_events_columns, "event")
    event_type_index = get_column_index(simplified_events_columns, "$event_type")
    current_url_index = get_column_index(simplified_events_columns, "$current_url")
    window_id_index = get_column_index(simplified_events_columns, "$window_id")
    session_start_time = prepare_datetime(session_start_time_str)

    total_events = len(simplified_events_mapping)
    summary_segments = []
    key_actions = []
    segment_outcomes = []

    for idx, segment in enumerate(segments):
        # Parse video segment timestamps to milliseconds
        start_ms = _parse_timestamp_to_ms(segment.start_time)
        end_ms = _parse_timestamp_to_ms(segment.end_time)

        # Find events within this segment's time range
        events_in_range = _find_events_in_time_range(
            start_ms=start_ms,
            end_ms=end_ms,
            simplified_events_mapping=simplified_events_mapping,
            simplified_events_columns=simplified_events_columns,
            session_start_time_str=session_start_time_str,
        )

        # If no events found in range, find closest events to segment boundaries
        if not events_in_range:
            start_event = _find_closest_event(
                target_ms=start_ms,
                simplified_events_mapping=simplified_events_mapping,
                simplified_events_columns=simplified_events_columns,
                session_start_time_str=session_start_time_str,
            )
            end_event = _find_closest_event(
                target_ms=end_ms,
                simplified_events_mapping=simplified_events_mapping,
                simplified_events_columns=simplified_events_columns,
                session_start_time_str=session_start_time_str,
            )
            if start_event:
                events_in_range = [start_event]
            if end_event and (not start_event or end_event[0] != start_event[0]):  # event[0] is the event_id
                events_in_range.append(end_event)

        # Get first and last events for segment boundaries
        if events_in_range:
            first_event_id, first_event_data = events_in_range[0]
            last_event_id, last_event_data = events_in_range[-1]

            # Calculate segment duration
            first_timestamp = first_event_data[timestamp_index]
            last_timestamp = last_event_data[timestamp_index]
            first_dt = prepare_datetime(first_timestamp)
            last_dt = prepare_datetime(last_timestamp)
            segment_duration = max(0, int((last_dt - first_dt).total_seconds()))
            duration_percentage = round(segment_duration / session_duration, 4) if session_duration > 0 else 0.0

            # Calculate events count
            events_count = len(events_in_range)
            events_percentage = round(events_count / total_events, 4) if total_events > 0 else 0.0
        else:
            # No events found, use placeholders
            first_event_id = f"vid_{idx:04d}_start"
            last_event_id = f"vid_{idx:04d}_end"
            segment_duration = 0
            duration_percentage = 0.0
            events_count = 0
            events_percentage = 0.0

        # Build segment entry - use detected flags from video analysis
        summary_segments.append(
            {
                "index": idx,
                "name": segment.title,
                "start_event_id": first_event_id,
                "end_event_id": last_event_id,
                "meta": {
                    "duration": segment_duration,
                    "duration_percentage": min(1.0, duration_percentage),
                    "events_count": events_count,
                    "events_percentage": min(1.0, events_percentage),
                    "key_action_count": 1,  # One key action per video segment
                    "failure_count": 1
                    if (segment.exception or segment.confusion_detected or segment.abandonment_detected)
                    else 0,
                    "abandonment_count": 1 if segment.abandonment_detected else 0,
                    "confusion_count": 1 if segment.confusion_detected else 0,
                    "exception_count": 1 if segment.exception else 0,
                },
            }
        )

        # Build key action with enriched event data
        # Use the first event in range for the key action, or create a synthetic one
        if events_in_range:
            representative_event_id, representative_event_data = events_in_range[0]

            # Calculate milliseconds since start
            event_timestamp = representative_event_data[timestamp_index]
            ms_since_start = calculate_time_since_start(event_timestamp, session_start_time)

            # Get URL and window ID
            current_url_key = representative_event_data[current_url_index]
            current_url = url_mapping_reversed.get(current_url_key) if current_url_key else None

            window_id_key = representative_event_data[window_id_index]
            window_id = window_mapping_reversed.get(window_id_key) if window_id_key else None

            # Get event name and type
            event_name = representative_event_data[event_name_index]
            event_type = representative_event_data[event_type_index]
            event_idx = representative_event_data[event_index_index]

            # Get real event UUID from mapping
            full_event_id = event_ids_mapping.get(representative_event_id)
            if full_event_id:
                try:
                    _, event_uuid = unpack_full_event_id(full_event_id, session_id)
                except ValueError:
                    event_uuid = None
            else:
                event_uuid = None

            key_action_event = {
                "description": segment.description,
                "abandonment": segment.abandonment_detected,
                "confusion": segment.confusion_detected,
                "exception": segment.exception,
                "event_id": representative_event_id,
                "timestamp": event_timestamp,
                "milliseconds_since_start": ms_since_start or 0,
                "current_url": current_url,
                "window_id": window_id,
                "event": event_name,
                "event_type": event_type,
                "event_index": event_idx,
                "session_id": session_id,
                "event_uuid": event_uuid,
            }
        else:
            # Fallback to synthetic event
            key_action_event = {
                "description": segment.description,
                "abandonment": segment.abandonment_detected,
                "confusion": segment.confusion_detected,
                "exception": segment.exception,
                "event_id": f"vid_{idx:04d}",
                "timestamp": segment.start_time,
                "milliseconds_since_start": start_ms,
                "current_url": None,
                "window_id": None,
                "event": "video_segment",
                "event_type": "video_analysis",
                "event_index": idx,
                "session_id": session_id,
                "event_uuid": None,
            }

        key_actions.append(
            {
                "segment_index": idx,
                "events": [key_action_event],
            }
        )

    # Use LLM-provided segment outcomes, or fall back to generating from segment data
    if analysis.segment_outcomes:
        segment_outcomes = [
            {
                "segment_index": outcome.segment_index,
                "summary": outcome.summary,
                "success": outcome.success,
            }
            for outcome in analysis.segment_outcomes
        ]
    else:
        segment_outcomes = [
            {
                "segment_index": idx,
                "summary": segment.description,
                "success": segment.success,
            }
            for idx, segment in enumerate(segments)
        ]

    # Use LLM-provided session outcome
    session_outcome = {
        "description": analysis.session_outcome.description,
        "success": analysis.session_outcome.success,
    }

    return {
        "segments": summary_segments,
        "key_actions": key_actions,
        "segment_outcomes": segment_outcomes,
        "session_outcome": session_outcome,
    }


def _parse_timestamp_to_ms(timestamp_str: str) -> int:
    """Parse MM:SS or HH:MM:SS timestamp string to milliseconds from session start"""
    parts = timestamp_str.split(":")
    if len(parts) == 2:
        # MM:SS format
        minutes, seconds = int(parts[0]), int(parts[1])
        return (minutes * 60 + seconds) * 1000
    elif len(parts) == 3:
        # HH:MM:SS format
        hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
        return (hours * 3600 + minutes * 60 + seconds) * 1000
    else:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}")


def _find_closest_event(
    target_ms: int,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    session_start_time_str: str,
) -> tuple[str, list[Any]] | None:
    """Find the event closest to the given timestamp (in milliseconds from session start)."""
    session_start_time = prepare_datetime(session_start_time_str)
    timestamp_index = get_column_index(simplified_events_columns, "timestamp")

    closest_event: tuple[str, list[Any]] | None = None
    min_diff = float("inf")

    for event_id, event_data in simplified_events_mapping.items():
        event_timestamp = event_data[timestamp_index]
        event_ms = calculate_time_since_start(event_timestamp, session_start_time)
        if event_ms is not None:
            diff = abs(event_ms - target_ms)
            if diff < min_diff:
                min_diff = diff
                closest_event = (event_id, event_data)

    return closest_event
