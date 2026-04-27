import re
import uuid
from datetime import timedelta
from textwrap import dedent
from typing import Any, Literal

from django.conf import settings
from django.utils.timezone import now

import structlog
from pydantic import BaseModel, Field
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.models import Team, User
from posthog.models.exported_asset import ExportedAsset
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.session_replay.rasterize_recording.types import RasterizeRecordingInputs
from posthog.temporal.session_replay.rasterize_recording.workflow import RasterizeRecordingWorkflow

from ee.hogai.session_summaries.constants import (
    DEFAULT_VIDEO_UNDERSTANDING_MODEL,
    EXPIRES_AFTER_DAYS,
    FULL_VIDEO_EXPORT_FORMAT,
)
from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError, MaxToolTransientError
from ee.hogai.videos.session_moments import GeminiVideoUnderstandingProvider

logger = structlog.get_logger(__name__)

# Max 2 minutes of wall clock active session duration
MAX_SEGMENT_DURATION_S = 120
# Same as full session summarization (a1_prep_session_video_asset.py)
VIDEO_ANALYSIS_PLAYBACK_SPEED = 8
VIDEO_ANALYSIS_RECORDING_FPS = 3

TIMESTAMP_PATTERN = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})$")


def parse_timestamp_to_seconds(timestamp: str) -> int:
    """Parse hh:mm:ss timestamp to total seconds."""
    match = TIMESTAMP_PATTERN.match(timestamp)
    if not match:
        raise ValueError(f"Invalid timestamp format '{timestamp}', expected hh:mm:ss")
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"Invalid timestamp '{timestamp}': minutes and seconds must be < 60")
    return hours * 3600 + minutes * 60 + seconds


def _session_belongs_to_team(*, team: Team, session_id: str) -> bool:
    from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

    replay_events = SessionReplayEvents()
    sessions_found, _, _ = replay_events.sessions_found_with_timestamps(session_ids=[session_id], team=team)
    return session_id in sessions_found


async def visually_analyze_session_segment(
    *,
    team: Team,
    user: User,
    session_id: str,
    start_timestamp: str,
    end_timestamp: str,
    angle: str,
) -> str:
    """
    Shared implementation for visual session segment analysis.

    Renders a segment of a session recording as video via Temporal,
    then analyzes it with Gemini. Used by both the MCP tool and the Max tool.

    Raises MaxToolRetryableError for input issues, MaxToolTransientError for infra issues.
    """
    # Parse and validate timestamps
    try:
        start_s = parse_timestamp_to_seconds(start_timestamp)
        end_s = parse_timestamp_to_seconds(end_timestamp)
    except ValueError as e:
        raise MaxToolRetryableError(str(e))

    if end_s <= start_s:
        raise MaxToolRetryableError(
            f"End timestamp ({end_timestamp}) must be after start timestamp ({start_timestamp})."
        )

    duration_s = end_s - start_s
    if duration_s > MAX_SEGMENT_DURATION_S:
        raise MaxToolRetryableError(
            f"The selected segment is {duration_s}s long, but the maximum supported duration is "
            f"{MAX_SEGMENT_DURATION_S}s (2 minutes). Please select a shorter time range."
        )

    session_belongs_to_team = await database_sync_to_async(_session_belongs_to_team, thread_sensitive=False)(
        team=team, session_id=session_id
    )
    if not session_belongs_to_team:
        raise MaxToolRetryableError("No session recording was found matching the provided session ID.")

    # Create ExportedAsset for the video segment
    created_at = now()
    expires_after = created_at + timedelta(days=EXPIRES_AFTER_DAYS)
    exported_asset = await ExportedAsset.objects.acreate(
        team_id=team.id,
        export_format=FULL_VIDEO_EXPORT_FORMAT,
        export_context={
            "session_recording_id": session_id,
            "timestamp": start_s,
            "duration": duration_s,
            "playback_speed": VIDEO_ANALYSIS_PLAYBACK_SPEED,
            "recording_fps": VIDEO_ANALYSIS_RECORDING_FPS,
            "show_metadata_footer": True,
        },
        created_by=user,
        created_at=created_at,
        expires_after=expires_after,
    )

    # Render video via Temporal workflow
    try:
        client = await async_connect()
        workflow_id = f"mcp-session-segment-video_{session_id}_{start_s}-{end_s}_{uuid.uuid4()}"
        await client.execute_workflow(
            RasterizeRecordingWorkflow.run,
            RasterizeRecordingInputs(exported_asset_id=exported_asset.id),
            id=workflow_id,
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=3),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            execution_timeout=timedelta(minutes=10),
        )
    except Exception as e:
        logger.exception(
            f"Failed to render video segment for session {session_id}: {e}",
            session_id=session_id,
            team_id=team.id,
        )
        # Clean up the asset
        await ExportedAsset.objects.filter(id=exported_asset.id).adelete()
        raise MaxToolTransientError(
            f"Failed to render video for the session segment. The video export service may be unavailable. Error: {e}"
        )

    # Retrieve video bytes
    video_bytes = await _get_video_bytes(exported_asset.id)
    if not video_bytes:
        raise MaxToolTransientError(
            "Video was rendered but could not be retrieved. The storage service may be unavailable."
        )

    # Analyze with Gemini
    provider = GeminiVideoUnderstandingProvider(model_id=DEFAULT_VIDEO_UNDERSTANDING_MODEL)
    prompt = (
        f"You are analyzing a segment of a web application session recording "
        f"(from {start_timestamp} to {end_timestamp} in the session).\n\n"
        f"Analysis angle: {angle}\n\n"
        f"Describe what you observe in this segment, focusing on the specified angle. "
        f"Be specific about user actions, UI states, and any notable behaviors or issues you see."
    )

    description = await provider.understand_video(
        video_bytes=video_bytes,
        mime_type=FULL_VIDEO_EXPORT_FORMAT,
        prompt=prompt,
    )

    if not description:
        raise MaxToolTransientError(
            "The video was rendered successfully but the visual analysis model returned no response. "
            "This may be due to the video being too short, too large, or a transient API issue."
        )

    return description


async def _get_video_bytes(asset_id: int) -> bytes | None:
    """Retrieve video content as bytes from an ExportedAsset."""
    try:
        # nosemgrep: idor-lookup-without-team (asset_id from internal creation, not user input)
        asset = await ExportedAsset.objects.aget(id=asset_id)
        if asset.content:
            return bytes(asset.content)
        elif asset.content_location:
            return await database_sync_to_async(object_storage.read_bytes, thread_sensitive=False)(
                asset.content_location
            )
        return None
    except ExportedAsset.DoesNotExist:
        return None


# ---------------------------------------------------------------------------
# Max tool (web PostHog AI)
# ---------------------------------------------------------------------------


class VisuallyAnalyzeSessionSegmentArgs(BaseModel):
    session_id: str = Field(description="The session recording ID to analyze.")
    start_timestamp: str = Field(description="Start timestamp within the session in hh:mm:ss format (e.g. '00:01:30').")
    end_timestamp: str = Field(description="End timestamp within the session in hh:mm:ss format (e.g. '00:03:00').")
    angle: str = Field(
        description="What to pay attention to when analyzing the video segment. "
        "For example: 'focus on user confusion around the checkout flow' or 'look for UI rendering issues'."
    )


class VisuallyAnalyzeSessionSegmentTool(MaxTool):
    name: Literal["visually_analyze_segment_of_session_recording"] = "visually_analyze_segment_of_session_recording"
    description: str = dedent(
        """
        Render a segment of a session recording as video and visually analyze it with an AI model.
        Provide a session recording ID, start and end timestamps (hh:mm:ss format), and an analysis
        angle describing what to focus on. Maximum supported segment duration is 2 minutes.
        Use this to understand what happened visually in a specific part of a session.
        """
    ).strip()
    args_schema: type[BaseModel] = VisuallyAnalyzeSessionSegmentArgs

    billable: bool = True

    def get_required_resource_access(self):
        return [("session_recording", "viewer")]

    async def _arun_impl(
        self,
        session_id: str,
        start_timestamp: str,
        end_timestamp: str,
        angle: str,
    ) -> tuple[str, Any]:
        result = await visually_analyze_session_segment(
            team=self._team,
            user=self._user,
            session_id=session_id,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            angle=angle,
        )
        return result, None
