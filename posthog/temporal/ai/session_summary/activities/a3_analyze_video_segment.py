"""
Activity 3 of the video-based summarization workflow:
Analyzing a specific segment of the session video with Gemini.
(Python modules have to start with a letter, hence the file is prefixed `a3_` instead of `3_`.)
"""

import re
import json
import time
from typing import Any, cast

from django.conf import settings

import temporalio
from google.genai import types
from posthoganalytics.ai.gemini import genai
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.ai.session_summary.types.video import (
    UploadedVideo,
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
)
from posthog.temporal.ai.session_summary.utils import format_seconds_as_mm_ss, parse_str_timestamp_to_s

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.tracking import capture_session_summary_timing
from ee.hogai.session_summaries.utils import calculate_time_since_start, get_column_index, prepare_datetime


@temporalio.activity.defn
async def analyze_video_segment_activity(
    inputs: VideoSummarySingleSessionInputs,
    uploaded_video: UploadedVideo,
    segment: VideoSegmentSpec,
    trace_id: str,
    team_name: str,
) -> list[VideoSegmentOutput]:
    """Analyze a segment of the uploaded video with Gemini using video_metadata for time range
    Returns detailed descriptions of salient moments in the segment.
    """
    start_time = time.monotonic()
    success = False
    try:
        # Retrieve cached event data from Redis (populated by fetch_session_data_activity)
        llm_input: SingleSessionSummaryLlmInputs | None = None
        events_context = ""
        if not inputs.redis_key_base:
            msg = "No Redis key base provided when analyzing video segment"
            temporalio.activity.logger.error(
                msg,
                extra={
                    "session_id": inputs.session_id,
                    "segment_index": segment.segment_index,
                    "signals_type": "session-summaries",
                },
            )
            # No need to retry, if the input is missing critical data, so it failed way before
            raise ApplicationError(msg, non_retryable=True)
        redis_client, redis_input_key, _ = get_redis_state_client(
            key_base=inputs.redis_key_base,
            input_label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=inputs.session_id,
        )
        llm_input_raw = await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            target_class=SingleSessionSummaryLlmInputs,
        )
        if llm_input_raw:
            llm_input = cast(SingleSessionSummaryLlmInputs, llm_input_raw)
            # Find events within this segment's time range, using session time, not video time
            start_ms = int(segment.start_time * 1000)
            end_ms = int(segment.end_time * 1000)
            events_in_range = _find_events_in_time_range(
                start_ms=start_ms,
                end_ms=end_ms,
                simplified_events_mapping=llm_input.simplified_events_mapping,
                simplified_events_columns=llm_input.simplified_events_columns,
                session_start_time_str=llm_input.session_start_time_str,
            )
            if events_in_range:
                events_context = _format_events_for_prompt(
                    events_in_range=events_in_range,
                    simplified_events_columns=llm_input.simplified_events_columns,
                    url_mapping_reversed=llm_input.url_mapping_reversed,
                    window_mapping_reversed=llm_input.window_mapping_reversed,
                )
                temporalio.activity.logger.debug(
                    f"Found {len(events_in_range)} events in segment {segment.segment_index} time range",
                    extra={
                        "session_id": inputs.session_id,
                        "segment_index": segment.segment_index,
                        "event_count": len(events_in_range),
                        "signals_type": "session-summaries",
                    },
                )
        # Construct analysis prompt
        start_timestamp_str = format_seconds_as_mm_ss(segment.recording_start_time)
        end_timestamp_str = format_seconds_as_mm_ss(segment.recording_end_time)
        # Calculating duration in video time, not session time
        segment_duration = segment.recording_end_time - segment.recording_start_time
        temporalio.activity.logger.debug(
            f"Analyzing segment {segment.segment_index} ({start_timestamp_str} - {end_timestamp_str}) for session {inputs.session_id}",
            extra={
                "session_id": inputs.session_id,
                "segment_index": segment.segment_index,
                "signals_type": "session-summaries",
            },
        )
        # Analyze with Gemini using video_metadata to specify the time range
        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
        video_analysis_prompt = VIDEO_SEGMENT_ANALYSIS_PROMPT.format(
            team_name=team_name,
            start_timestamp=start_timestamp_str,
            segment_duration=segment_duration,
            events_section=VIDEO_SEGMENT_ANALYSIS_PROMPT_EVENTS_SECTION.format(events_context=events_context)
            if events_context
            else "",
        )
        response = await client.models.generate_content(
            model=f"models/{inputs.model_to_use}",
            contents=[
                types.Part(
                    file_data=types.FileData(file_uri=uploaded_video.file_uri, mime_type=uploaded_video.mime_type),
                    # Round, as Gemini doesn't work with nanoseconds
                    video_metadata=types.VideoMetadata(
                        start_offset=f"{round(segment.recording_start_time, 2)}s",
                        end_offset=f"{round(segment.recording_end_time, 2)}s",
                    ),
                ),
                video_analysis_prompt,
            ],
            config=types.GenerateContentConfig(),
            posthog_distinct_id=inputs.user_distinct_id_to_log,
            posthog_trace_id=trace_id,
            posthog_properties={
                "$session_id": inputs.session_id,
                "segment_index": segment.segment_index,
            },
            posthog_groups={"project": str(inputs.team_id)},
        )
        response_text = (response.text or "").strip()
        temporalio.activity.logger.debug(
            f"Received analysis for segment {segment.segment_index}",
            extra={
                "session_id": inputs.session_id,
                "segment_index": segment.segment_index,
                "response_length": len(response_text),
                "response_preview": response_text[:200] if response_text else None,
                "signals_type": "session-summaries",
            },
        )
        # Parse response into segments
        segments = []
        # Parse bullet points in format: * MM:SS - MM:SS: description
        pattern_colon = r"\*\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2}):\s*(.+?)(?=\n\*|$)"
        matches = re.findall(pattern_colon, response_text, re.DOTALL | re.MULTILINE)
        if not matches:
            temporalio.activity.logger.warning(
                f"No segments matched regex pattern for segment {segment.segment_index}",
                extra={
                    "session_id": inputs.session_id,
                    "segment_index": segment.segment_index,
                    "response_text": response_text[:500],
                    "signals_type": "session-summaries",
                },
            )
        # Iterate over description + start/end time matches from the LLM response to store what happend during the analyzed segment
        for match_start_time_str, match_end_time_str, match_description in matches:
            match_description = match_description.strip()
            if not match_description:
                # Nothing described, so nothing to store
                continue
            # Check if the timestamps are parseable
            try:
                # Match timestamps are video-based as LLM generated them based on video
                match_start_time_s = parse_str_timestamp_to_s(match_start_time_str)
                match_end_time_s = parse_str_timestamp_to_s(match_end_time_str)
            except ValueError:
                temporalio.activity.logger.warning(
                    "Skipping segment with invalid timestamp",
                    extra={
                        "session_id": inputs.session_id,
                        "segment_index": segment.segment_index,
                        "start_time": match_start_time_str,
                        "end_time": match_end_time_str,
                        "signals_type": "session-summaries",
                    },
                )
                continue
            # Check if the end timestamp is after the start timestamp
            if match_end_time_s < match_start_time_s:
                temporalio.activity.logger.warning(
                    "Skipping segment with invalid time range",
                    extra={
                        "session_id": inputs.session_id,
                        "segment_index": segment.segment_index,
                        "start_time": match_start_time_str,
                        "end_time": match_end_time_str,
                        "signals_type": "session-summaries",
                    },
                )
                continue
            # Calculate how much time passed since the segment started in video time
            start_seconds_since_segment_start = max(round(match_start_time_s - segment.recording_start_time, 2), 0)
            end_seconds_since_segment_start = max(round(match_end_time_s - segment.recording_start_time, 2), 0)
            # Calculate the timestamps in session time
            session_time_start_str = format_seconds_as_mm_ss(segment.start_time + start_seconds_since_segment_start)
            session_time_end_str = format_seconds_as_mm_ss(segment.start_time + end_seconds_since_segment_start)
            # Collect the data
            segments.append(
                VideoSegmentOutput(
                    start_time=session_time_start_str,
                    end_time=session_time_end_str,
                    description=match_description,
                )
            )

        temporalio.activity.logger.debug(
            f"Parsed {len(segments)} segments from segment {segment.segment_index}",
            extra={
                "session_id": inputs.session_id,
                "segment_index": segment.segment_index,
                "segment_count": len(segments),
                "signals_type": "session-summaries",
            },
        )

        success = True
        return segments

    except Exception as e:
        temporalio.activity.logger.exception(
            f"Failed to analyze segment {segment.segment_index} for session {inputs.session_id}: {e}",
            extra={
                "session_id": inputs.session_id,
                "segment_index": segment.segment_index,
                "signals_type": "session-summaries",
                "segment_start_time": segment.start_time,
                "segment_end_time": segment.end_time,
                "video_file_uri": uploaded_video.file_uri,
                "video_duration_seconds": uploaded_video.duration,
                "model": inputs.model_to_use,
            },
        )
        raise
    finally:
        duration_seconds = time.monotonic() - start_time
        team = await Team.objects.aget(id=inputs.team_id)
        capture_session_summary_timing(
            user_distinct_id=inputs.user_distinct_id_to_log,
            team=team,
            session_id=inputs.session_id,
            timing_type="transcript",
            duration_seconds=duration_seconds,
            success=success,
            extra_properties={
                "segment_index": segment.segment_index,
                "segment_start_time": segment.start_time,
                "segment_end_time": segment.end_time,
            },
        )


VIDEO_SEGMENT_ANALYSIS_PROMPT = """
Analyze this video segment from a session recording of a user using {team_name}.

This segment starts at {start_timestamp} in the full recording and runs for approximately {segment_duration:.0f} seconds.
{events_section}
Your task:
- Describe what's happening in the video as a list of salient moments
- Highlight what features were used, and what the user was doing with them
- Note any problems, errors, confusion, or friction the user experienced
- If tracked events show exceptions ($exception_types, $exception_values), validate if they happened in the video
- Red lines indicate mouse movements, and should be ignored
- If nothing is happening, return "Static" for the timestamp range

Output format (use timestamps relative to the FULL recording, starting at {start_timestamp}):
* MM:SS - MM:SS: <detailed description>
* MM:SS - MM:SS: <detailed description>
* etc.

Be specific and detailed about:
- What the user clicked on
- What pages or sections they navigated to
- What they typed or entered
- Any errors or loading states (correlate with exception events if available)
- Signs of confusion or hesitation
- What outcomes occurred

Example output:
* 0:16 - 0:18: User clicked on the dashboard navigation item in the sidebar
* 0:18 - 0:24: User scrolled through the dashboard page viewing multiple analytics widgets
* 0:24 - 0:25: User clicked "Create new project" button in the top toolbar
* 0:25 - 0:32: User filled out the project creation form, entering name and description
* 0:32 - 0:33: User attempted to submit the form but received validation error "Name is required"

IMPORTANT: Use timestamps relative to the full recording (starting at {start_timestamp}), not relative to this segment.
"""

VIDEO_SEGMENT_ANALYSIS_PROMPT_EVENTS_SECTION = """
<tracked_events>
The following events were tracked during this segment. Use them to understand what actions the user took
and correlate them with what you see in the video. Pay special attention to:
- $exception_types and $exception_values: These indicate errors or exceptions that occurred
- elements_chain_texts: Text content the user interacted with
- $event_type: The type of interaction (click, submit, etc.)
- $current_url: The page URL where the action occurred

Events data (in chronological order):
{events_context}
</tracked_events>
"""


def _format_events_for_prompt(
    events_in_range: list[tuple[str, list[Any]]],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
) -> str:
    """Format events data for inclusion in the video analysis prompt"""
    if not events_in_range:
        return "No tracked events occurred during this segment."

    # Build a simplified view of events for the prompt
    # Include key columns that help understand what happened
    key_columns = [
        "event_id",
        "event_index",
        "event",
        "timestamp",
        "$event_type",
        "$current_url",
        "elements_chain_texts",
        "$exception_types",
        "$exception_values",
    ]

    # Get indices for key columns
    column_indices: dict[str, int | None] = {}
    for col in key_columns:
        try:
            column_indices[col] = get_column_index(simplified_events_columns, col)
        except ValueError:
            column_indices[col] = None

    # Format events
    formatted_events = []
    for event_id, event_data in events_in_range:
        event_info: dict[str, Any] = {"event_id": event_id}
        for col in key_columns:
            idx = column_indices.get(col)
            if idx is not None and idx < len(event_data):
                value = event_data[idx]
                if value is not None:
                    # Resolve URL and window mappings
                    if col == "$current_url" and isinstance(value, str):
                        value = url_mapping_reversed.get(value, value)
                    elif col == "$window_id" and isinstance(value, str):
                        value = window_mapping_reversed.get(value, value)
                    event_info[col] = value
        formatted_events.append(event_info)

    # TODO: Use CSV format instead of JSON for fewer tokens
    return json.dumps(formatted_events, indent=2, default=str)


def _find_events_in_time_range(
    start_ms: int,
    end_ms: int,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    session_start_time_str: str,
) -> list[tuple[str, list[Any]]]:
    """Find all events that fall within the given time range (in milliseconds from session start).

    Returns a list of (event_id, event_data) tuples sorted by event_index.
    """
    session_start_time = prepare_datetime(session_start_time_str)
    timestamp_index = get_column_index(simplified_events_columns, "timestamp")
    event_index_index = get_column_index(simplified_events_columns, "event_index")

    events_in_range: list[tuple[str, list[Any], int]] = []

    for event_id, event_data in simplified_events_mapping.items():
        event_timestamp = event_data[timestamp_index]
        event_ms = calculate_time_since_start(event_timestamp, session_start_time)
        if event_ms is not None and start_ms <= event_ms <= end_ms:
            event_index = event_data[event_index_index]
            events_in_range.append((event_id, event_data, event_index))

    # Sort by event_index
    events_in_range.sort(key=lambda x: x[2])

    return [(event_id, event_data) for event_id, event_data, _ in events_in_range]
