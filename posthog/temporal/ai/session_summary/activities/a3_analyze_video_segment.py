import re
import json
from typing import Any, cast

from django.conf import settings

import structlog
import temporalio
from google.genai import types, Client

from posthog.models.team.team import Team
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.ai.session_summary.types.video import (
    UploadedVideo,
    VideoSegmentElement,
    VideoSegmentInteractionsEnum,
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSegmentTypesEnum,
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
                    logger.info(
                        f"Found {len(events_in_range)} events in segment {segment.segment_index} time range",
                        session_id=inputs.session_id,
                        segment_index=segment.segment_index,
                        event_count=len(events_in_range),
                    )

        # Construct analysis prompt
        start_timestamp = _format_timestamp(segment.start_time)
        end_timestamp = _format_timestamp(segment.end_time)
        segment_duration = segment.end_time - segment.start_time

        logger.info(
            f"Analyzing segment {segment.segment_index} ({start_timestamp} - {end_timestamp}) for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
        )

        team_name = (await Team.objects.only("name").aget(id=inputs.team_id)).name

        # Analyze with Gemini using video_metadata to specify the time range
        client = Client(api_key=settings.GEMINI_API_KEY)

        # TODO: Add additional call to combine trasncription with events
        # events_section=(
        #                 VIDEO_SEGMENT_ANALYSIS_PROMPT_EVENTS_SECTION.format(events_context=events_context)
        #                 if events_context
        #                 else ""
        #             ),
        # TODO: Use posthoganalytics wrapper for async calls (update posthoganalytics version?)
        response = await client.aio.models.generate_content(
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
                    element_types = ",".join(f"`{x.value}`" for x in VideoSegmentTypesEnum),
                    interaction_types = ",".join(f"`{x.value}`" for x in VideoSegmentInteractionsEnum),
                ),
            ],
            config=types.GenerateContentConfig(max_output_tokens=4096),
            # posthog_distinct_id=inputs.user_distinct_id_to_log,
            # posthog_trace_id=trace_id,
            # posthog_properties={
            #     "$session_id": inputs.session_id,
            #     "segment_index": segment.segment_index,
            # },
            # posthog_groups={"project": str(inputs.team_id)},
        )

        response_text = (response.text or "").strip()

        logger.info(
            f"Received analysis for segment {segment.segment_index}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
            response_length=len(response_text),
            response_preview=response_text[:200] if response_text else None,
        )

        if response_text.lower() == "static":
            # No activity in this segment
            logger.debug(
                f"Segment {segment.segment_index} marked as static",
                session_id=inputs.session_id,
                segment_index=segment.segment_index,
            )
            return []

        # Parse response into segments
        segments = VideoSegmentParser().parse_response_into_segment_outputs(response_text)

        logger.info(
            f"Parsed {len(segments)} segments from segment {segment.segment_index}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
            segment_count=len(segments),
        )

        return segments

    except Exception as e:
        logger.exception(
            f"Failed to analyze segment {segment.segment_index} for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
        )
        raise


VIDEO_SEGMENT_ANALYSIS_PROMPT = """
# Task
Analyze this video segment from a session recording of a user using "{team_name}".

This segment starts at {start_timestamp} in the full recording and runs for approximately {segment_duration:.0f} seconds.

## What to focus on
- Describe what's happening in the video as a list of salient moments
- Highlight what features were used, and what the user was doing with them
- Explicitly mention names/labels of the elements the user interacted with
- Note any problems, errors, confusion, or friction the user experienced
- Notice clicks, as they are indicated by magenta circle around cursors

## What to ignore
- Ignore red lines that indicate mouse movements
- Ignore accidental hovers
- Don't list clicks if they are not confirmed visually
- If the segment or the point within the segment has no activity - return "MM:SS - MM:SS: Static"

## Granularity
- Describe at the maximum granularity possible
- Any explicit user interactions or navigations should get a separate point into the output list
- If the point covers more than 5 seconds - split it
- If the point covers more than 1 interaction - split it

## Output format

Return the output in the following markdown format:

```
- **MM:SS - MM:SS**: <detailed description of the user action>
  `elements: element_type="label_1", element_type="label_2"`
  `interaction: interaction_type`
- ...
```

- `element_type` is one of: {element_types}
- IMPORTANT: If you want to assign multiple elements with the same type to a single point - create a new point instead
- `interaction_type` is one of: {interaction_types}
- IMPORTANT: Use timestamps relative to the FULL recording, starting at {start_timestamp})

## Example output

- **00:01 - 00:04**: The user inputs their email address into the Email input field on the PostHog Cloud login page.
  `elements: page_title="PostHog Cloud", input="Email"`
  `interaction: input`
"""

## TODO - Reuse events in the additional call
VIDEO_SEGMENT_EVENTS_ENRICHMENT_PROMPT = """
# Task
Attach events to the relevant points in the description of the segment of session recordings.

This segment starts at {start_timestamp} in the full recording and runs for approximately {segment_duration:.0f} seconds.

The following events were tracked during this segment. Use them to understand what actions the user took
and correlate them with what you see in the video. Pay special attention to:
- $exception_types and $exception_values: These indicate errors or exceptions that occurred
- elements_chain_texts: Text content the user interacted with
- $event_type: The type of interaction (click, submit, etc.)
- $current_url: The page URL where the action occurred

Events data (in chronological order):
{events_context}
"""


class VideoSegmentParser:

    def _parse_elements(self, elements_raw: str) -> list[VideoSegmentElement]:
        elements_raw = elements_raw.strip().strip("`")
        if not elements_raw.startswith("elements:"):
            msg = f"Unexpected elements field: {elements_raw}"
            logger.error(msg, signals_type="session-summaries")
            raise ValueError(msg)
        content = elements_raw.split("elements:")[-1]
        if not content:
            return
        elements = []
        # Match key="value" or key=["a", "b"]
        pattern = r'(\w+)=(\[[^\]]+\]|"[^"]*")'
        # Not validating with enums, as LLM can return custom values, so focusing on parsing the values
        for key, value in re.findall(pattern, content):
            # Parse array: ["Email", "Password"]
            if value.startswith("["):
                found_elements = re.findall(r'"([^"]*)"', value)
                if not found_elements:
                    logger.warning(f"No elements found for value: {value}", signals_type="session-summaries")
                    continue
                for element in found_elements:
                    try:
                        element_type = VideoSegmentTypesEnum(key).value
                    except ValueError:
                        logger.warning(
                            f'Unknown element type for value "{value}": {key}, using custom',
                            signals_type="session-summaries",
                        )
                        element_type = VideoSegmentTypesEnum.CUSTOM.value
                    elements.append(VideoSegmentElement(element_type=element_type, element_value=element))
            # Parse single: "Email"
            else:
                try:
                    element_type = VideoSegmentTypesEnum(key).value
                except ValueError:
                    logger.warning(
                        f'Unknown element type for value "{value}": {key}, using custom',
                        signals_type="session-summaries",
                    )
                    element_type = VideoSegmentTypesEnum.CUSTOM.value
                elements.append(VideoSegmentElement(element_type=element_type, element_value=value.strip('"')))
        return elements

    def _parse_interaction(self, interaction_raw: str) -> str:
        interaction_raw = interaction_raw.strip().strip("`")
        if not interaction_raw.startswith("interaction:"):
            raise ValueError(f"Unexpected interaction field: {interaction_raw}")
        interaction = interaction_raw.split("interaction:")[-1].strip()
        try:
            interaction_type = VideoSegmentInteractionsEnum(interaction).value
        except ValueError:
            logger.warning(f"Unknown interaction type: {interaction}, using custom", signals_type="session-summaries")
            interaction_type = VideoSegmentInteractionsEnum.CUSTOM.value
        return interaction_type

    def parse_response_into_segment_outputs(self, response_text: str) -> list[VideoSegmentOutput]:
        points: list[VideoSegmentOutput] = []
        segment_pattern = r"-\s+\*\*(\d{1,2}:\d{1,2})\s*-\s*(\d{1,2}:\d{1,2})\*\*:\s*((?:.|\n\s)*?)(?=(?:\n-|$))"
        matches = re.findall(segment_pattern, response_text)
        for point_pattern_match in matches:
            # If no elements or interaction are present
            if len(point_pattern_match) == 2:
                start_time, end_time = point_pattern_match
                points.append(
                    VideoSegmentOutput(
                        start_time=start_time,
                        end_time=end_time,
                        description="",
                        elements=None,
                        interaction=None,
                    )
                )
                continue
            # If description part is present
            if len(point_pattern_match) == 3:
                start_time, end_time, description = point_pattern_match
                description_parts = description.split("\n")
                # If only description is present
                if len(description_parts) == 1:
                    description = description_parts[0]
                    points.append(
                        VideoSegmentOutput(
                            start_time=start_time,
                            end_time=end_time,
                            description=description,
                            elements=None,
                            interaction=None,
                        )
                    )
                    continue
                # If description and at least one meta field is present
                if len(description_parts) == 2:
                    description, meta_field = description_parts
                    try:
                        # Try to parse elements
                        elements = self._parse_elements(meta_field)
                        interaction = None
                    except ValueError:
                        try:
                            # If no elements present, try to parse interaction
                            interaction = self._parse_interaction(meta_field)
                            elements = None
                        except ValueError:
                            msg = f"Unexpected meta field: {meta_field}"
                            logger.error(msg, signals_type="session-summaries")
                            raise ValueError(msg)
                    points.append(
                        VideoSegmentOutput(
                            start_time=start_time,
                            end_time=end_time,
                            description=description,
                            elements=elements,
                            interaction=interaction,
                        )
                    )
                    continue
                # If description and both meta fields are present
                if len(description_parts) == 3:
                    description, elements_raw, interaction_raw = description_parts
                    elements = self._parse_elements(elements_raw)
                    interaction = self._parse_interaction(interaction_raw)
                    points.append(
                        VideoSegmentOutput(
                            start_time=start_time,
                            end_time=end_time,
                            description=description,
                            elements=elements,
                            interaction=interaction,
                        )
                    )
                    continue
                else:
                    msg = f"Unexpected number of parts: {len(description_parts)}"
                    logger.error(msg, signals_type="session-summaries")
                    raise ValueError(msg)
            else:
                msg = f"Unexpected number of matches: {len(matches)}"
                logger.error(msg, signals_type="session-summaries")
                raise ValueError(msg)
        return points


def _format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS"""
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
        column_indices[col] = get_column_index(simplified_events_columns, col)

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
