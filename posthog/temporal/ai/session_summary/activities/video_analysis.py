import re
import json
import time
import tempfile
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from django.conf import settings
from django.utils.timezone import now

import structlog
import temporalio
from google.genai import (
    Client as RawGenAIClient,
    types,
)
from posthoganalytics.ai.gemini import genai
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.models.exported_asset import ExportedAsset
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.ai.session_summary.types.video import (
    ConsolidatedVideoSegment,
    UploadedVideo,
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
)
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs, VideoExportWorkflow

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_EXPORT_MIME_TYPE
from ee.hogai.session_summaries.session.input_data import get_team
from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs
from ee.hogai.session_summaries.utils import (
    calculate_time_since_start,
    get_column_index,
    prepare_datetime,
    unpack_full_event_id,
)

logger = structlog.get_logger(__name__)

# Embedding model to use
EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072

# Chunk duration in seconds
CHUNK_DURATION = 15


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


def _format_timestamp(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def _get_video_duration(video_path: str) -> float:
    """Get duration of video in seconds using ffprobe"""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(result.stdout.strip())
    except Exception as e:
        logger.exception(f"Failed to get video duration: {e}")
        raise


@temporalio.activity.defn
async def export_session_video_activity(inputs: VideoSummarySingleSessionInputs) -> int:
    """Export full session video and return ExportedAsset ID"""
    try:
        # Check for existing exported asset for this session
        existing_asset = (
            await ExportedAsset.objects.filter(
                team_id=inputs.team_id,
                export_format=DEFAULT_VIDEO_EXPORT_MIME_TYPE,
                export_context__session_recording_id=inputs.session_id,
            )
            .exclude(content_location__isnull=True, content__isnull=True)
            .afirst()
        )

        if existing_asset:
            logger.info(
                f"Found existing video export for session {inputs.session_id}, reusing asset {existing_asset.id}",
                session_id=inputs.session_id,
                asset_id=existing_asset.id,
            )
            return existing_asset.id

        # Get session duration from metadata
        team = await database_sync_to_async(get_team)(team_id=inputs.team_id)
        metadata = await database_sync_to_async(SessionReplayEvents().get_metadata)(
            session_id=inputs.session_id,
            team=team,
        )
        if not metadata:
            raise ValueError(f"No metadata found for session {inputs.session_id}")
        session_duration = metadata["duration"]  # duration is in seconds

        # Create filename for the video
        import uuid

        filename = f"session-video-summary_{inputs.session_id}_{uuid.uuid4()}"

        # Create ExportedAsset
        created_at = now()
        # Keep indefinitely - set expires_after to far future
        expires_after = created_at + timedelta(days=365 * 10)  # 10 years

        exported_asset = await ExportedAsset.objects.acreate(
            team_id=inputs.team_id,
            export_format=DEFAULT_VIDEO_EXPORT_MIME_TYPE,
            export_context={
                "session_recording_id": inputs.session_id,
                "timestamp": 0,  # Start from beginning
                "filename": filename,
                "duration": session_duration,
                "playback_speed": 1.0,  # Normal speed
                "mode": "screenshot",
            },
            created_by_id=inputs.user_id,
            created_at=created_at,
            expires_after=expires_after,
        )

        # Execute VideoExportWorkflow
        client = await async_connect()
        await client.execute_workflow(
            VideoExportWorkflow.run,
            VideoExportInputs(exported_asset_id=exported_asset.id),
            id=f"session-video-summary-export_{inputs.session_id}_{uuid.uuid4()}",
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )

        logger.info(
            f"Video exported successfully for session {inputs.session_id}",
            session_id=inputs.session_id,
            asset_id=exported_asset.id,
        )

        return exported_asset.id

    except Exception as e:
        logger.exception(
            f"Failed to export video for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
        )
        raise


@temporalio.activity.defn
async def upload_video_to_gemini_activity(inputs: VideoSummarySingleSessionInputs, asset_id: int) -> UploadedVideo:
    """Upload full video to Gemini for analysis and return file reference with duration"""
    try:
        # Get video bytes from ExportedAsset
        asset = await ExportedAsset.objects.aget(id=asset_id)

        video_bytes: bytes | None = None
        if asset.content:
            video_bytes = bytes(asset.content)
        elif asset.content_location:
            video_bytes = await database_sync_to_async(object_storage.read_bytes, thread_sensitive=False)(
                asset.content_location
            )

        if not video_bytes:
            msg = f"No video content found for asset {asset_id} for session {inputs.session_id}"
            logger.error(msg, session_id=inputs.session_id, asset_id=asset_id)
            raise ValueError(msg)

        # Write video to temporary file for upload and duration check
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            tmp_file.write(video_bytes)
            tmp_file_path = tmp_file.name

        try:
            # Get video duration
            duration = _get_video_duration(tmp_file_path)
            logger.info(
                f"Video duration: {duration:.2f} seconds",
                session_id=inputs.session_id,
                duration=duration,
            )

            # Upload to Gemini
            raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)

            logger.info(
                f"Uploading full video to Gemini for session {inputs.session_id}",
                session_id=inputs.session_id,
                video_size_bytes=len(video_bytes),
            )

            uploaded_file = raw_client.files.upload(file=tmp_file_path)

            # Wait for processing
            while uploaded_file.state and uploaded_file.state.name == "PROCESSING":
                time.sleep(1)
                if not uploaded_file.name:
                    raise RuntimeError("Uploaded file has no name for status polling")
                uploaded_file = raw_client.files.get(name=uploaded_file.name)

            state_name = uploaded_file.state.name if uploaded_file.state else None
            if state_name != "ACTIVE":
                raise RuntimeError(f"File processing failed. State: {state_name}")

            if not uploaded_file.uri:
                raise RuntimeError("Uploaded file has no URI")

            logger.info(
                f"Video uploaded successfully to Gemini for session {inputs.session_id}",
                session_id=inputs.session_id,
                file_uri=uploaded_file.uri,
                duration=duration,
            )

            return UploadedVideo(
                file_uri=uploaded_file.uri,
                mime_type=uploaded_file.mime_type or "video/mp4",
                duration=duration,
            )

        finally:
            # Clean up temporary file
            Path(tmp_file_path).unlink(missing_ok=True)

    except Exception as e:
        logger.exception(
            f"Failed to upload video to Gemini for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
        )
        raise


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

    return json.dumps(formatted_events, indent=2, default=str)


@temporalio.activity.defn
async def analyze_video_segment_activity(
    inputs: VideoSummarySingleSessionInputs,
    uploaded_video: UploadedVideo,
    segment: VideoSegmentSpec,
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

        # Use wrapped client for generation (with PostHog observability)
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        # Construct analysis prompt
        start_timestamp = _format_timestamp(segment.start_time)
        end_timestamp = _format_timestamp(segment.end_time)
        segment_duration = segment.end_time - segment.start_time

        # Build events context section for the prompt
        events_section = ""
        if events_context:
            events_section = f"""
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

        prompt = f"""Analyze this video segment from a web analytics session recording.

This segment starts at {start_timestamp} in the full recording and runs for approximately {segment_duration:.0f} seconds.
{events_section}
Your task:
- Describe what's happening in the video as a list of salient moments
- Highlight what features were used, and what the user was doing with them
- Note any problems, errors, confusion, or friction the user experienced
- If tracked events show exceptions ($exception_types, $exception_values), identify them in your analysis
- Red lines indicate mouse movements, and should be ignored
- If nothing is happening, return "Static"

Output format (use timestamps relative to the FULL recording, starting at {start_timestamp}):
* MM:SS - MM:SS: <detailed description>
* MM:SS - MM:SS: <detailed description>

Be specific and detailed about:
- What the user clicked on
- What pages or sections they navigated to
- What they typed or entered
- Any errors or loading states (correlate with exception events if available)
- Signs of confusion or hesitation
- What outcomes occurred

Example output:
* {start_timestamp} - {_format_timestamp(segment.start_time + 3)}: User navigated to the dashboard page and viewed the recent activity widget showing 5 new events
* {_format_timestamp(segment.start_time + 3)} - {_format_timestamp(segment.start_time + 8)}: User clicked on "Create new project" button in the top toolbar
* {_format_timestamp(segment.start_time + 8)} - {end_timestamp}: User attempted to submit the form but received validation error "Name is required"

IMPORTANT: Use timestamps relative to the full recording (starting at {start_timestamp}), not relative to this segment.
"""

        logger.info(
            f"Analyzing segment {segment.segment_index} ({start_timestamp} - {end_timestamp}) for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
        )

        # Analyze with Gemini using video_metadata to specify the time range
        response = client.models.generate_content(
            model=f"models/{inputs.model_to_use}",
            contents=[
                types.Part(
                    file_data=types.FileData(file_uri=uploaded_video.file_uri, mime_type=uploaded_video.mime_type),
                    video_metadata=types.VideoMetadata(
                        start_offset=f"{segment.start_time}s",
                        end_offset=f"{segment.end_time}s",
                    ),
                ),
                prompt,
            ],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(include_thoughts=False),
                max_output_tokens=4096,
            ),
            posthog_distinct_id=inputs.user_distinct_id_to_log,
            posthog_trace_id=f"video-analysis-{inputs.redis_key_base}-{inputs.session_id}",
            posthog_properties={
                "$session_id": inputs.session_id,
                "segment_index": segment.segment_index,
            },
            posthog_groups={"project": str(inputs.team_id)},
        )

        response_text = (response.text or "").strip()

        logger.info(
            f"Received analysis for segment {segment.segment_index}",
            session_id=inputs.session_id,
            segment_index=segment.segment_index,
            response_length=len(response_text),
            response_preview=response_text[:200] if response_text else None,
        )

        # Parse response into segments
        segments = []

        if response_text.lower() == "static":
            # No activity in this segment
            logger.debug(
                f"Segment {segment.segment_index} marked as static",
                session_id=inputs.session_id,
                segment_index=segment.segment_index,
            )
            return []

        # Parse bullet points in format: * MM:SS - MM:SS: description
        pattern_colon = r"\*\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?):\s*(.+?)(?=\n\*|$)"

        matches = re.findall(pattern_colon, response_text, re.DOTALL | re.MULTILINE)

        if not matches:
            logger.warning(
                f"No segments matched regex pattern for segment {segment.segment_index}",
                session_id=inputs.session_id,
                segment_index=segment.segment_index,
                response_text=response_text[:500],
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


@temporalio.activity.defn
async def consolidate_video_segments_activity(
    inputs: VideoSummarySingleSessionInputs,
    raw_segments: list[VideoSegmentOutput],
) -> list[ConsolidatedVideoSegment]:
    """Consolidate raw video segments into meaningful semantic segments using LLM.

    Takes the raw segments from video analysis (which have generic timestamps but no meaningful titles)
    and asks an LLM to reorganize them into semantically meaningful segments with proper titles.

    This preserves all information while creating logical groupings like:
    - "User onboarding flow"
    - "Debugging API configuration"
    - "Exploring dashboard features"
    """
    if not raw_segments:
        return []

    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        # Format raw segments for the prompt
        segments_text = "\n".join(f"- **{seg.start_time} - {seg.end_time}:** {seg.description}" for seg in raw_segments)

        prompt = f"""You are analyzing a session recording from a web analytics product. Below are timestamped descriptions of what the user did during the session.

Your task is to consolidate these into meaningful semantic segments. Each segment should:
1. Have a **descriptive title** that captures the user's goal or activity (e.g., "Setting up integration", "Exploring analytics dashboard", "Debugging API errors")
2. Span a coherent period of related activity (combine adjacent segments that are part of the same task)
3. Have a **combined description** that synthesizes the details from the original segments
4. Preserve ALL important information from the original descriptions - don't lose any details

Raw segments:
{segments_text}

Output format (JSON array):
```json
[
  {{
    "title": "Descriptive segment title",
    "start_time": "MM:SS",
    "end_time": "MM:SS",
    "description": "Combined description of what happened in this segment, preserving all important details from the original segments"
  }}
]
```

Rules:
- Create 3-10 segments depending on session complexity (fewer for short simple sessions, more for long complex ones)
- Titles should be specific and actionable (avoid generic titles like "User activity" or "Browsing")
- Time ranges must not overlap and should cover the full session
- Preserve error messages, specific UI elements clicked, and outcomes mentioned in original segments
- Keep descriptions concise but complete

Output ONLY the JSON array, no other text."""

        logger.info(
            f"Consolidating {len(raw_segments)} raw segments for session {inputs.session_id}",
            session_id=inputs.session_id,
            raw_segment_count=len(raw_segments),
        )

        response = client.models.generate_content(
            model="models/gemini-2.5-flash",
            contents=[prompt],
            config=types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(include_thoughts=False),
                max_output_tokens=4096,
            ),
            posthog_distinct_id=inputs.user_distinct_id_to_log,
            posthog_trace_id=f"video-consolidation-{inputs.redis_key_base}-{inputs.session_id}",
            posthog_properties={"$session_id": inputs.session_id},
            posthog_groups={"project": str(inputs.team_id)},
        )

        response_text = (response.text or "").strip()

        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", response_text)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text

        parsed = json.loads(json_str)

        consolidated_segments = [
            ConsolidatedVideoSegment(
                title=item["title"],
                start_time=item["start_time"],
                end_time=item["end_time"],
                description=item["description"],
            )
            for item in parsed
        ]

        logger.info(
            f"Consolidated {len(raw_segments)} raw segments into {len(consolidated_segments)} semantic segments",
            session_id=inputs.session_id,
            raw_count=len(raw_segments),
            consolidated_count=len(consolidated_segments),
        )

        return consolidated_segments

    except Exception as e:
        logger.exception(
            f"Failed to consolidate segments for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
        )
        # Re-raise to let the workflow retry with proper retry policy
        raise


@temporalio.activity.defn
async def embed_and_store_segments_activity(
    inputs: VideoSummarySingleSessionInputs,
    segments: list[VideoSegmentOutput],
    asset_id: int,
) -> None:
    """Generate embeddings for all segments and produce to Kafka for ClickHouse storage

    Each segment description is embedded with metadata including session_id, team_id,
    distinct_id, and timestamps.
    """
    try:
        if not segments:
            logger.info(
                f"No segments to embed for session {inputs.session_id}",
                session_id=inputs.session_id,
            )
            return

        for segment in segments:
            # Use the description directly as the content to embed
            content = segment.description

            # Create unique document ID
            document_id = f"{inputs.session_id}:{segment.start_time}:{segment.end_time}"

            # Include structured metadata for querying/filtering
            metadata = {
                "session_id": inputs.session_id,
                "team_id": inputs.team_id,
                "distinct_id": inputs.user_distinct_id_to_log,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
            }

            emit_embedding_request(
                team_id=inputs.team_id,
                product="session-replay",
                document_type="video-segment",
                rendering="video-analysis",
                document_id=document_id,
                content=content,
                models=[EMBEDDING_MODEL.value],
                metadata=metadata,
            )

            logger.debug(
                f"Produced embedding for segment {document_id}",
                session_id=inputs.session_id,
                document_id=document_id,
            )

        logger.info(
            f"Successfully produced {len(segments)} embeddings for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_count=len(segments),
        )

    except Exception as e:
        logger.exception(
            f"Failed to embed and store segments for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
        )
        raise


def _convert_video_segments_to_session_summary(
    segments: list[ConsolidatedVideoSegment],
    session_id: str,
    llm_input: SingleSessionSummaryLlmInputs | None = None,
) -> dict:
    """Convert video segments to session summary format

    When llm_input is provided (from Redis cache), maps video segments to real events:
    - Uses timestamps to find events within each segment's time range
    - Populates real event IDs, UUIDs, and metadata from the cached event data
    - Calculates accurate segment metadata (duration, events count, etc.)

    When llm_input is not available, falls back to placeholder data.
    """
    if not llm_input:
        # Fallback to placeholder-based summary if no cached event data available
        return _convert_video_segments_to_session_summary_fallback(segments, session_id)

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
            if end_event and end_event != start_event:
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

        # Build segment entry
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
                    "failure_count": 0,
                    "abandonment_count": 0,
                    "confusion_count": 0,
                    "exception_count": 0,
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
                "abandonment": False,
                "confusion": False,
                "exception": None,
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
                "abandonment": False,
                "confusion": False,
                "exception": None,
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

        # Create segment outcome
        segment_outcomes.append(
            {
                "segment_index": idx,
                "summary": segment.description,
                "success": True,  # Default to success for video segments
            }
        )

    # Create overall session outcome
    session_outcome = {
        "description": f"Video-based analysis of session with {len(segments)} segments identified",
        "success": True,
    }

    return {
        "segments": summary_segments,
        "key_actions": key_actions,
        "segment_outcomes": segment_outcomes,
        "session_outcome": session_outcome,
    }


def _convert_video_segments_to_session_summary_fallback(
    segments: list[ConsolidatedVideoSegment],
    session_id: str,
) -> dict:
    """Fallback conversion when no cached event data is available.

    Uses placeholder event IDs and minimal metadata.
    """
    summary_segments = []
    key_actions = []
    segment_outcomes = []

    for idx, segment in enumerate(segments):
        start_ms = _parse_timestamp_to_ms(segment.start_time)

        summary_segments.append(
            {
                "index": idx,
                "name": segment.title,
                "start_event_id": f"vid_{idx:04d}_start",
                "end_event_id": f"vid_{idx:04d}_end",
                "meta": {
                    "duration": 0,
                    "duration_percentage": 0.0,
                    "events_count": 0,
                    "events_percentage": 0.0,
                    "key_action_count": 1,
                    "failure_count": 0,
                    "abandonment_count": 0,
                    "confusion_count": 0,
                    "exception_count": 0,
                },
            }
        )

        key_actions.append(
            {
                "segment_index": idx,
                "events": [
                    {
                        "description": segment.description,
                        "abandonment": False,
                        "confusion": False,
                        "exception": None,
                        "event_id": f"vid_{idx:04d}",
                        "timestamp": segment.start_time,
                        "milliseconds_since_start": start_ms,
                        "current_url": None,
                        "event": "video_segment",
                        "event_type": "video_analysis",
                        "event_index": idx,
                        "session_id": session_id,
                        "event_uuid": None,
                    }
                ],
            }
        )

        segment_outcomes.append(
            {
                "segment_index": idx,
                "summary": segment.description,
                "success": True,
            }
        )

    session_outcome = {
        "description": f"Video-based analysis of session with {len(segments)} segments identified",
        "success": True,
    }

    return {
        "segments": summary_segments,
        "key_actions": key_actions,
        "segment_outcomes": segment_outcomes,
        "session_outcome": session_outcome,
    }


@temporalio.activity.defn
async def store_video_session_summary_activity(
    inputs: VideoSummarySingleSessionInputs,
    segments: list[ConsolidatedVideoSegment],
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
            logger.info(
                f"Video-based summary already exists for session {inputs.session_id}, skipping storage",
                session_id=inputs.session_id,
            )
            return

        # Retrieve cached event data from Redis (populated by fetch_session_data_activity)
        llm_input: SingleSessionSummaryLlmInputs | None = None
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
                logger.info(
                    f"Retrieved cached event data for video summary alignment, session {inputs.session_id}",
                    session_id=inputs.session_id,
                    event_count=len(llm_input.simplified_events_mapping),
                )
            else:
                logger.warning(
                    f"No cached event data found for session {inputs.session_id}, using fallback summary format",
                    session_id=inputs.session_id,
                )

        # Convert video segments to session summary format, using real events if available
        summary_dict = _convert_video_segments_to_session_summary(
            segments=segments,
            session_id=inputs.session_id,
            llm_input=llm_input,
        )

        # Validate the summary - use streaming validation only if we don't have real event data
        use_streaming_validation = llm_input is None
        session_summary = SessionSummarySerializer(
            data=summary_dict, context={"streaming_validation": use_streaming_validation}
        )
        if not session_summary.is_valid():
            msg = f"Failed to validate video-based summary for session {inputs.session_id}: {session_summary.errors}"
            logger.error(msg, session_id=inputs.session_id)
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

        logger.info(
            f"Successfully stored video-based summary for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_count=len(segments),
            has_real_events=llm_input is not None,
        )

    except Exception as e:
        logger.exception(
            f"Failed to store video-based summary for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
        )
        raise
