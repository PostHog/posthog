"""
Activity 2 of the video-based summarization workflow:
Uploading the exported session video to Gemini.
(Python modules have to start with a letter, hence the file is prefixed `a2_` instead of `2_`.)
"""

import time
import asyncio
import tempfile

from django.conf import settings

import structlog
import temporalio
from google.genai import (
    Client as RawGenAIClient,
    types,
)

from posthog.models.exported_asset import ExportedAsset
from posthog.models.team.team import Team
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.video import (
    UploadedVideo,
    UploadVideoToGeminiOutput,
    VideoSummarySingleSessionInputs,
)

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_EXPORT_MIME_TYPE
from ee.hogai.videos.utils import get_video_duration_s

logger = structlog.get_logger(__name__)


# Timeout: 5 minutes (activity timeout is 10 minutes, leaving buffer for other operations)
MAX_PROCESSING_WAIT_SECONDS = 300


@temporalio.activity.defn
async def upload_video_to_gemini_activity(
    inputs: VideoSummarySingleSessionInputs, asset_id: int
) -> UploadVideoToGeminiOutput:
    """Upload full video to Gemini for analysis and return file reference with duration, plus team name"""
    try:
        # Fetch team name once here to avoid fetching it 100+ times in parallel segment analysis
        team_name = (await Team.objects.only("name").aget(id=inputs.team_id)).name
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
            logger.error(msg, session_id=inputs.session_id, asset_id=asset_id, signals_type="session-summaries")
            raise ValueError(msg)

        duration = get_video_duration_s(video_bytes)

        # Write video to temporary file for upload
        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.write(video_bytes)
            tmp_file.flush()  # Ensure data is flushed to disk before reading by path
            # Upload to Gemini
            logger.debug(
                f"Uploading full video to Gemini for session {inputs.session_id}",
                duration=duration,
                session_id=inputs.session_id,
                video_size_bytes=len(video_bytes),
                signals_type="session-summaries",
            )
            raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)
            uploaded_file = raw_client.files.upload(
                file=tmp_file.name, config=types.UploadFileConfig(mime_type=asset.export_format)
            )
            # Wait for file to be ready
            wait_start_time = time.time()
            while uploaded_file.state and uploaded_file.state.name == "PROCESSING":
                elapsed = time.time() - wait_start_time
                if elapsed >= MAX_PROCESSING_WAIT_SECONDS:
                    raise RuntimeError(
                        f"File processing timed out after {elapsed:.1f}s. "
                        f"File may still be processing on Gemini's side. State: {uploaded_file.state.name}"
                    )
                await asyncio.sleep(0.5)
                logger.debug(
                    f"Waiting for file to be ready: {uploaded_file.state.name}",
                    session_id=inputs.session_id,
                    file_name=uploaded_file.name,
                    file_state=uploaded_file.state.name,
                    elapsed_seconds=elapsed,
                    signals_type="session-summaries",
                )
                if not uploaded_file.name:
                    raise RuntimeError("Uploaded file has no name for status polling")
                uploaded_file = raw_client.files.get(name=uploaded_file.name)
            final_state_name = uploaded_file.state.name if uploaded_file.state else None
            if final_state_name != "ACTIVE":
                raise RuntimeError(f"File processing failed. State: {final_state_name}")
            if not uploaded_file.uri:
                raise RuntimeError("Uploaded file has no URI")
            logger.debug(
                f"Video uploaded successfully to Gemini for session {inputs.session_id}",
                session_id=inputs.session_id,
                file_uri=uploaded_file.uri,
                duration=duration,
                signals_type="session-summaries",
            )

            uploaded_video = UploadedVideo(
                file_uri=uploaded_file.uri,
                mime_type=uploaded_file.mime_type or DEFAULT_VIDEO_EXPORT_MIME_TYPE,
                duration=duration,
            )
            return UploadVideoToGeminiOutput(uploaded_video=uploaded_video, team_name=team_name)

    except Exception as e:
        logger.exception(
            f"Failed to upload video to Gemini for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        raise
