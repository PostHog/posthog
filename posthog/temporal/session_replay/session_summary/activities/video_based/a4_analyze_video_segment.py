import re
import json
from typing import Any, cast

from django.conf import settings

import temporalio
from google.genai import types
from posthoganalytics.ai.gemini import genai
from temporalio.exceptions import ApplicationError

from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    SegmentLlmContext,
    UploadedVideo,
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
)
from posthog.temporal.session_replay.session_summary.utils import format_seconds_as_mm_ss, parse_str_timestamp_to_s

from ee.hogai.session_summaries.utils import calculate_time_since_start, get_column_index, prepare_datetime


@temporalio.activity.defn
async def analyze_video_segment_activity(
    inputs: VideoSummarySingleSessionInputs,
    uploaded_video: UploadedVideo,
    segment: VideoSegmentSpec,
    trace_id: str,
    team_name: str,
) -> list[VideoSegmentOutput]:
    try:
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
        redis_client, _, _ = get_redis_state_client(key_base=inputs.redis_key_base)
        segment_state_id = f"{inputs.session_id}:{segment.segment_index}"
        segment_key = generate_state_key(
            key_base=inputs.redis_key_base,
            label=StateActivitiesEnum.SEGMENT_LLM_CONTEXT,
            state_id=segment_state_id,
        )
        segment_context_raw = await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=segment_key,
            label=StateActivitiesEnum.SEGMENT_LLM_CONTEXT,
            target_class=SegmentLlmContext,
        )
        if segment_context_raw:
            segment_context = cast(SegmentLlmContext, segment_context_raw)
            if segment_context.events:
                events_context = _format_events_for_prompt(
                    events=[(entry.event_id, entry.data) for entry in segment_context.events],
                    simplified_events_columns=segment_context.simplified_events_columns,
                    url_mapping_reversed=segment_context.url_mapping_reversed,
                    window_mapping_reversed=segment_context.window_mapping_reversed,
                )
                temporalio.activity.logger.debug(
                    f"Found {len(segment_context.events)} events in segment {segment.segment_index} time range",
                    extra={
                        "session_id": inputs.session_id,
                        "segment_index": segment.segment_index,
                        "event_count": len(segment_context.events),
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


VIDEO_SEGMENT_ANALYSIS_PROMPT = """
Analyze this video segment from a session recording of a user using {team_name}.

This segment starts at {start_timestamp} in the full recording and runs for approximately {segment_duration:.0f} seconds.
{events_section}
Your task:
- Describe what the user did and how it went. Group related actions together — not every click is a separate entry.
- Cover what went smoothly and what didn't — don't only report problems.
- Mention errors only when they visibly affected the user (error on screen, page failed to load, action didn't complete). Ignore background console errors with no visible impact.
- Note confusion (backtracking, repeated attempts, rage clicking) only when clearly present.
- Red lines indicate mouse movements — ignore them.
- If nothing is happening, return "Static" for the timestamp range.

Output format (use timestamps relative to the FULL recording, starting at {start_timestamp}):
* MM:SS - MM:SS: <what happened and the outcome>

Include:
- Which features, pages, or sections were involved (use names visible on screen)
- Whether the user finished what they were doing or left
- Specific error messages only when visible on screen

Example output:
* 0:16 - 0:24: Opened the analytics dashboard, scrolled through pageview and conversion trend widgets
* 0:24 - 0:33: Went to project creation — filled out the form, clicked submit, but got a "Name is required" error. Tried again with the same result and left the page

IMPORTANT: Use timestamps relative to the full recording (starting at {start_timestamp}), not relative to this segment.
"""

VIDEO_SEGMENT_ANALYSIS_PROMPT_EVENTS_SECTION = """
<tracked_events>
The following events were tracked during this segment. Use them to understand what actions the user took
and correlate them with what you see in the video:
- elements_chain_texts: Text content the user interacted with
- $event_type: The type of interaction (click, submit, etc.)
- $current_url: The page URL where the action occurred
- $exception_types and $exception_values: These indicate errors logged in the console. IMPORTANT: Only mention an exception if it visibly affected what the user was doing (e.g., an error message appeared on screen, a page failed to load, an action didn't complete). Many console errors are background noise — do not attribute them to the user's actions unless there is a clear visual connection.

Events data (in chronological order):
{events_context}
</tracked_events>
"""


def _format_events_for_prompt(
    events: list[tuple[str, list[Any]]],
    simplified_events_columns: list[str],
    url_mapping_reversed: dict[str, str],
    window_mapping_reversed: dict[str, str],
) -> str:
    """Format events data for inclusion in the video analysis prompt"""
    if not events:
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
    for event_id, event_data in events:
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
