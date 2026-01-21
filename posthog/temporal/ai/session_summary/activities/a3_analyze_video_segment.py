"""
Activity 3 of the video-based summarization workflow:
Analyzing a specific segment of the session video with Gemini.
(Python modules have to start with a letter, hence the file is prefixed `a3_` instead of `3_`.)
"""

import re
import json
from typing import Any, cast

from django.conf import settings

import structlog
import temporalio
from google.genai import types
from posthoganalytics.ai.gemini import genai

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

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import calculate_time_since_start, get_column_index, prepare_datetime

SESSION_VIDEO_CHUNK_DURATION_S = 15

logger = structlog.get_logger(__name__)


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
    try:
        # Retrieve cached event data from Redis (populated by fetch_session_data_activity)
        llm_input: SingleSessionSummaryLlmInputs | None = None
        events_context = ""
        if inputs.redis_key_base:
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

                # Find events within this segment's time range
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
                    logger.debug(
                        f"Found {len(events_in_range)} events in segment {segment.segment_index} time range",
                        session_id=inputs.session_id,
                        segment_index=segment.segment_index,
                        event_count=len(events_in_range),
                        signals_type="session-summaries",
                    )

        # Construct analysis prompt
        start_timestamp = _format_timestamp_as_mm_ss(segment.start_time)
        end_timestamp = _format_timestamp_as_mm_ss(segment.end_time)
        segment_duration = segment.end_time - segment.start_time

        logger.debug(
            f"Analyzing segment {segment.segment_index} ({start_timestamp} - {end_timestamp}) for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
            signals_type="session-summaries",
        )

        # Analyze with Gemini using video_metadata to specify the time range
        client = genai.AsyncClient(api_key=settings.GEMINI_API_KEY)
        response = await client.models.generate_content(
            model=f"models/{inputs.model_to_use}",
            contents=[
                types.Part(
                    file_data=types.FileData(file_uri=uploaded_video.file_uri, mime_type=uploaded_video.mime_type),
                    video_metadata=types.VideoMetadata(
                        start_offset=f"{segment.start_time}s",
                        end_offset=f"{segment.end_time}s",
                    ),
                ),
                VIDEO_SEGMENT_ANALYSIS_PROMPT.format(
                    team_name=team_name,
                    start_timestamp=start_timestamp,
                    segment_duration=segment_duration,
                    events_section=VIDEO_SEGMENT_ANALYSIS_PROMPT_EVENTS_SECTION.format(events_context=events_context)
                    if events_context
                    else "",
                ),
            ],
            config=types.GenerateContentConfig(max_output_tokens=4096),
            posthog_distinct_id=inputs.user_distinct_id_to_log,
            posthog_trace_id=trace_id,
            posthog_properties={
                "$session_id": inputs.session_id,
                "segment_index": segment.segment_index,
            },
            posthog_groups={"project": str(inputs.team_id)},
        )

        response_text = (response.text or "").strip()

        logger.debug(
            f"Received analysis for segment {segment.segment_index}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
            response_length=len(response_text),
            response_preview=response_text[:200] if response_text else None,
            signals_type="session-summaries",
        )

        # Parse response into segments
        segments = []

        # Parse bullet points in format: * MM:SS - MM:SS: description
        pattern_colon = r"\*\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2}):\s*(.+?)(?=\n\*|$)"

        matches = re.findall(pattern_colon, response_text, re.DOTALL | re.MULTILINE)

        if not matches:
            logger.warning(
                f"No segments matched regex pattern for segment {segment.segment_index}",
                session_id=inputs.session_id,
                segment_index=segment.segment_index,
                response_text=response_text[:500],
                signals_type="session-summaries",
            )

        for start_time_str, end_time_str, description in matches:
            description = description.strip()
            if description:
                segments.append(
                    VideoSegmentOutput(
                        start_time=start_time_str,
                        end_time=end_time_str,
                        description=description,
                    )
                )

        logger.debug(
            f"Parsed {len(segments)} segments from segment {segment.segment_index}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
            segment_count=len(segments),
            signals_type="session-summaries",
        )

        return segments

    except Exception as e:
        logger.exception(
            f"Failed to analyze segment {segment.segment_index} for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
            signals_type="session-summaries",
        )
        raise


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


def _format_timestamp_as_mm_ss(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


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
