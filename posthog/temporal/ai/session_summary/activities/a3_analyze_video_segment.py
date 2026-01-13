"""
Activity 3 of the video-based summarization workflow:
Analyzing a specific segment of the session video with Gemini.
(Python modules have to start with a letter, hence the file is prefixed `a3_` instead of `3_`.)
"""

import re
from datetime import datetime
from math import floor
from statistics import median
from typing import Any, cast

from django.conf import settings

import structlog
import temporalio
from google.genai import types
from posthoganalytics.ai.gemini import genai

from posthog.models.team.team import Team
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.ai.session_summary.types.video import (
    UploadedVideo,
    VideoSegmentElement,
    VideoSegmentInteraction,
    VideoSegmentInteractionsEnum,
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSegmentTypesEnum,
    VideoSummarySingleSessionInputs,
)

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import calculate_time_since_start, get_column_index, prepare_datetime

# TODO: Split not by seconds, but by periods of inactivity and navigation events
SESSION_VIDEO_CHUNK_DURATION_S = 60

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
        # Construct analysis prompt
        start_timestamp = _format_timestamp_as_mm_ss(segment.start_time)
        end_timestamp = _format_timestamp_as_mm_ss(segment.end_time)
        segment_duration = segment.end_time - segment.start_time

        logger.debug(
            f"Analyzing segment {segment.segment_index} ({start_timestamp} - {end_timestamp}) for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
        )

        # We can't do async operations at the workflow level, so we have to fetch team_name in each individual activity here
        team_name = (await Team.objects.only("name").aget(id=inputs.team_id)).name

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
                        fps=3,  # Increased FPS to get clicks properly (0.33s animation on click)
                    ),
                ),
                VIDEO_SEGMENT_ANALYSIS_PROMPT.format(
                    team_name=team_name,
                    start_timestamp=start_timestamp,
                    segment_duration=segment_duration,
                    element_types=",".join(f"`{x.value}`" for x in VideoSegmentTypesEnum),
                    interaction_types=",".join(f"`{x.value}`" for x in VideoSegmentInteractionsEnum),
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
        )

        # Parse response into segments
        segments = VideoSegmentParser().parse_response_into_segment_outputs(response_text)
        if not segments:
            logger.warning(
                f"No segments found for segment {segment.segment_index}",
                session_id=inputs.session_id,
                segment_index=segment.segment_index,
            )
            return []

        logger.debug(
            f"Parsed {len(segments)} segments from segment {segment.segment_index}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
            segment_count=len(segments),
        )

        # If no data in Redis - no events to process
        if not inputs.redis_key_base:
            return segments

        # If no segments with indicators - we can't reliably attach events, so returning segments as is
        segments_with_indicators = [segment for segment in segments if segment.timestamp_indicator]
        if not segments_with_indicators:
            logger.warning(
                f"No segments with timestamp indicators found for segment {segment.segment_index}",
                session_id=inputs.session_id,
                segment_index=segment.segment_index,
            )
            return segments

        # Add relevant events as interactions
        segments_with_interactions = await VideoSegmentEventsEnricher().add_relevant_events_as_interactions(
            segments_with_indicators=segments_with_indicators,
            segment_spec=segment,
            redis_key_base=inputs.redis_key_base,
            session_id=inputs.session_id,
        )
        if segments_with_interactions:
            return segments_with_interactions
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
- If tracked events show exceptions ($exception_types, $exception_values), validate if they happened in the video
- Red lines indicate mouse movements, and should be ignored
- If nothing is happening, return "Static" for the timestamp range

## Indicators
Video includes additional video indicators for LLMs specifically, and are not visible to the user:

- Clicks are indicated by magenta circle around cursors
- Mouse movements are indicated by a moving red line
- Bottom of the video includes a black line with additional metadata:
    - Current `URL`, use it to better understand the page's context
    - `REC_T` indicator, use it to populate the `rec_t` field in the output
    - Optional `IDLE` indicator, if present - user didn't move mouse or click buttons

Avoid mentioning these indicators in the output, as they are not part of the recording and added for analysis purposes only.

Example output:
* 0:16 - 0:18: User clicked on the dashboard navigation item in the sidebar
* 0:18 - 0:24: User scrolled through the dashboard page viewing multiple analytics widgets
* 0:24 - 0:25: User clicked "Create new project" button in the top toolbar
* 0:25 - 0:32: User filled out the project creation form, entering name and description
* 0:32 - 0:33: User attempted to submit the form but received validation error "Name is required"

## What to ignore
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
  `rec_t: REC_T`
- ...
```

- `element_type` is one of: {element_types}
- IMPORTANT: If you want to assign multiple elements with the same type to a single point - create a new point instead
- `interaction_type` is one of: {interaction_types}
- `rec_t` - the value of the `REC_T` indicator at the bottom of the video

## Example output

- **02:07 - 02:10**: The user inputs their email address into the Email input field on the PostHog Cloud login page.
  `elements: page_title="PostHog Cloud", input="Email"`
  `interaction: input`
  `rec_t: 119`
"""


class VideoSegmentParser:
    def _parse_description(self, description_raw: str) -> str | None:
        description_pattern = (
            r"^(.*)?(?:\n+\s*`|$)"  # First line till the first ` after a new line or the end of the string
        )
        results = re.findall(description_pattern, description_raw)
        if not results:
            # We expect the description to be present at all times
            logger.exception(f"No description found in: {description_raw}", signals_type="session-summaries")
            return None
        return results[0]

    def _parse_elements(self, description_raw: str) -> list[VideoSegmentElement] | None:
        elements_pattern = r"\s*`elements:\s*(.*)?`(?:\n|$)"
        results = re.findall(elements_pattern, description_raw)
        if not results:
            # It's ok for elements to be missing
            return None
        content = results[0].strip()
        if not content:
            return None
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

    def _parse_interaction(self, description_raw: str) -> str | None:
        interaction_pattern = r"\s*`interaction:\s*(.*)?`(?:\n|$)"
        results = re.findall(interaction_pattern, description_raw)
        if not results:
            # It's ok for interaction to be missing
            return None
        interaction = results[0].strip()
        try:
            interaction_type = VideoSegmentInteractionsEnum(interaction).value
        except ValueError:
            logger.warning(f"Unknown interaction type: {interaction}, using custom", signals_type="session-summaries")
            interaction_type = VideoSegmentInteractionsEnum.CUSTOM.value
        return interaction_type

    def _parse_timestamp_indicator(self, description_raw: str) -> int | None:
        timestamp_indicator_pattern = r"\s*`rec_t:\s*(.*)?`(?:\n|$)"
        results = re.findall(timestamp_indicator_pattern, description_raw)
        if not results:
            # We expect the timestamp indicator to be present at all times
            logger.exception(f"No timestamp indicator found in: {description_raw}", signals_type="session-summaries")
            return None
        timestamp_indicator = results[0].strip()
        # If returns the range - stick only to the start, as the main purpose it to link the interaction to the session timeline
        if "-" in timestamp_indicator:
            timestamp_indicator = timestamp_indicator.split("-")[0]
        return int(timestamp_indicator)

    def parse_response_into_segment_outputs(self, response_text: str) -> list[VideoSegmentOutput]:
        points: list[VideoSegmentOutput] = []
        segment_pattern = r"-\s+\*\*(\d{1,2}:\d{1,2})\s*-\s*(\d{1,2}:\d{1,2})\*\*:\s*((?:.|\n\s)*?)(?=(?:\n-|$))"
        matches = re.findall(segment_pattern, response_text)
        for point_pattern_match in matches:
            # If no elements or interaction are present
            if len(point_pattern_match) == 2:
                start_time, end_time = point_pattern_match
                points.append(VideoSegmentOutput(start_time=start_time, end_time=end_time, description=""))
                continue
            # If description part is present - extract meta fields
            if len(point_pattern_match) == 3:
                start_time, end_time, description = point_pattern_match
                description_raw = description.strip()
                description = self._parse_description(description_raw)
                elements = self._parse_elements(description_raw)
                interaction_type = self._parse_interaction(description_raw)
                timestamp_indicator = self._parse_timestamp_indicator(description_raw)
                # If no interaction metadata
                if not interaction_type and not elements:
                    interactions = None
                # If only elements
                elif not interaction_type and elements:
                    interactions = [
                        VideoSegmentInteraction(
                            interaction_source="video",
                            interaction_type=VideoSegmentInteractionsEnum.CUSTOM.value,
                            elements=elements,
                            s_from_start=timestamp_indicator,
                        )
                    ]
                # If only interaction
                elif interaction_type and not elements:
                    interactions = [
                        VideoSegmentInteraction(
                            interaction_source="video",
                            interaction_type=interaction_type,
                            s_from_start=timestamp_indicator,
                        )
                    ]
                # If both interaction and elements
                elif interaction_type and elements:
                    interactions = [
                        VideoSegmentInteraction(
                            interaction_source="video",
                            interaction_type=interaction_type,
                            elements=elements,
                            s_from_start=timestamp_indicator,
                        )
                    ]
                else:
                    # Keep mypy happy
                    interactions = None
                points.append(
                    VideoSegmentOutput(
                        start_time=start_time,
                        end_time=end_time,
                        description=description,
                        interactions=interactions,
                        # Using the same indicator for the segment and interaction as segment IS interaction, just with more context
                        timestamp_indicator=timestamp_indicator,
                    )
                )
        return points


class VideoSegmentEventsEnricher:
    def _pick_relevant_events(
        self,
        events_in_range: list[tuple[str, list[Any]]],
        simplified_events_columns: list[str],
        session_start_time: datetime,
    ) -> list[VideoSegmentInteraction] | None:
        if not events_in_range:
            return None
        interactions: list[VideoSegmentInteraction] = []
        # Pick only meaning-heavy context from the events
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
        # Convert events to interactions
        # TODO: Also include event id (`_` below) in the schema for better linking to other data
        for _, event_data in events_in_range:
            # Ensure all required column indices are available
            event_idx = column_indices["event"]
            event_type_idx = column_indices["$event_type"]
            timestamp_idx = column_indices["timestamp"]
            elements_chain_texts_idx = column_indices["elements_chain_texts"]

            if event_idx is None or event_type_idx is None or timestamp_idx is None or elements_chain_texts_idx is None:
                continue

            # Keep only clicks for the initial version, as they are the most reliable events
            event = event_data[event_idx]
            event_type = event_data[event_type_idx]
            timestamp_str = event_data[timestamp_idx]
            timestamp_s = int(calculate_time_since_start(timestamp_str, session_start_time) / 1000)
            if event != "$autocapture" and event_type != "click":
                continue
            # Keep only clicks that have text context attached to mean anything
            elements_chain_texts = event_data[elements_chain_texts_idx]
            if not elements_chain_texts:
                continue
            # Convert click into interaction
            event_interaction = VideoSegmentInteraction(
                interaction_source="events",
                interaction_type=VideoSegmentInteractionsEnum.CLICK.value,
                elements=[
                    VideoSegmentElement(element_type=VideoSegmentTypesEnum.LABEL.value, element_value=label)
                    for label in elements_chain_texts
                ],
                s_from_start=timestamp_s,
            )
            interactions.append(event_interaction)
        return interactions

    async def add_relevant_events_as_interactions(
        self,
        segments_with_indicators: list[VideoSegmentOutput],
        segment_spec: VideoSegmentSpec,
        redis_key_base: str,
        session_id: str,
    ) -> list[VideoSegmentOutput] | None:
        # Calculate the average start offset of the points within the segment - the difference between video timestamp and timestamp indicator
        # The assumption that timestamp indicator and start of the point should be close, so offset could be reliably applied to events search
        events_offset_s = max(
            0,
            floor(
                median(
                    # The assumption that the video timestamps is either later (rendering delays) or the same as the timestamp indicator
                    _parse_timestamp_to_seconds(segment.start_time) - segment.timestamp_indicator
                    for segment in segments_with_indicators
                    if segment.timestamp_indicator is not None
                )
            ),
        )
        # Get events using the offset
        redis_client, redis_input_key, _ = get_redis_state_client(
            key_base=redis_key_base,
            input_label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=session_id,
        )
        llm_input_raw = await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            target_class=SingleSessionSummaryLlmInputs,
        )
        if not llm_input_raw:
            return None
        llm_input = cast(SingleSessionSummaryLlmInputs, llm_input_raw)
        session_start_time = prepare_datetime(llm_input.session_start_time_str)

        # Iterate over segments to attach relevant events as interactions, using the offset
        updated_segments = []
        for segment in segments_with_indicators:
            # Find events within this segment's time range, adjusting for the events offset
            start_ms = int((_parse_timestamp_to_seconds(segment.start_time) - events_offset_s) * 1000)
            end_ms = int((_parse_timestamp_to_seconds(segment.end_time) - events_offset_s) * 1000)
            events_in_range = _find_events_in_time_range(
                start_ms=start_ms,
                end_ms=end_ms,
                simplified_events_mapping=llm_input.simplified_events_mapping,
                simplified_events_columns=llm_input.simplified_events_columns,
                session_start_time=session_start_time,
            )
            if not events_in_range:
                return None
            logger.info(
                f"Found {len(events_in_range)} events in segment {segment_spec.segment_index} time range",
                session_id=session_id,
                segment_index=segment_spec.segment_index,
                event_count=len(events_in_range),
            )
            relevant_events = self._pick_relevant_events(
                events_in_range=events_in_range,
                simplified_events_columns=llm_input.simplified_events_columns,
                session_start_time=session_start_time,
            )
            if relevant_events:
                # Initialize interactions list if it doesn't exist
                if segment.interactions is None:
                    segment.interactions = []
                segment.interactions.extend(relevant_events)
            # Sort interactions by s_from_start if interactions exist
            if segment.interactions:
                segment.interactions.sort(key=lambda x: x.s_from_start if x.s_from_start is not None else 0)
            # TODO: Remove duplicates - both video and events marked the same click
            updated_segments.append(segment)
        return updated_segments


def _parse_timestamp_to_seconds(time_str: str) -> int:
    parts = list(map(int, time_str.split(":")))
    seconds = 0
    for i, part in enumerate(reversed(parts)):
        seconds += part * (60**i)
    return seconds


def _format_timestamp_as_mm_ss(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def _find_events_in_time_range(
    start_ms: int,
    end_ms: int,
    simplified_events_mapping: dict[str, list[Any]],
    simplified_events_columns: list[str],
    session_start_time: datetime,
) -> list[tuple[str, list[Any]]]:
    """Find all events that fall within the given time range (in milliseconds from session start).

    Returns a list of (event_id, event_data) tuples sorted by event_index.
    """
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
