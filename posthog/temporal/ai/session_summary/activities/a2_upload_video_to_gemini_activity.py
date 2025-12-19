import time
import tempfile
import subprocess
from pathlib import Path

from django.conf import settings

import structlog
import temporalio
from google.genai import Client as RawGenAIClient

from posthog.models.exported_asset import ExportedAsset
from posthog.storage import object_storage
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.video import UploadedVideo, VideoSummarySingleSessionInputs

logger = structlog.get_logger(__name__)


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
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_file:
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

            # Wait for file to be ready
            while uploaded_file.state and uploaded_file.state.name == "PROCESSING":
                time.sleep(0.5)  # Gotta do polling sadly
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
