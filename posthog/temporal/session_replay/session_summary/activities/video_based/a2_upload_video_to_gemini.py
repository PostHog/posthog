import time
import asyncio
import tempfile
from datetime import UTC, datetime

from django.conf import settings

import structlog
import temporalio
from asgiref.sync import sync_to_async
from google.genai import (
    Client as RawGenAIClient,
    types,
)

from posthog.schema import ReplayInactivityPeriod

from posthog.models.exported_asset import ExportedAsset
from posthog.storage import object_storage
from posthog.temporal.session_replay.gemini_cleanup_sweep.tracking import track_uploaded_file
from posthog.temporal.session_replay.session_summary.types.video import (
    UploadedVideo,
    UploadVideoToGeminiOutput,
    VideoSummarySingleSessionInputs,
)

from ee.hogai.session_summaries.constants import MOMENT_VIDEO_EXPORT_FORMAT
from ee.hogai.videos.utils import get_video_duration_s

logger = structlog.get_logger(__name__)


# Activity timeout is 10 minutes; this leaves buffer for the rest of the activity body.
MAX_PROCESSING_WAIT_SECONDS = 300


@temporalio.activity.defn
async def upload_video_to_gemini_activity(
    inputs: VideoSummarySingleSessionInputs, asset_id: int
) -> UploadVideoToGeminiOutput:
    """Upload full video to Gemini and return file reference with duration.

    Tracking happens before the ACTIVE-wait so a polling timeout still leaves the file visible
    to the sweep. On track failure the just-uploaded file is deleted inline.
    """
    workflow_id = temporalio.activity.info().workflow_id
    if workflow_id is None:
        raise RuntimeError("activity has no workflow_id")
    try:
        asset = await ExportedAsset.objects.aget(id=asset_id)

        video_bytes: bytes | None = None
        if asset.content:
            video_bytes = bytes(asset.content)
        elif asset.content_location:
            video_bytes = await sync_to_async(object_storage.read_bytes, thread_sensitive=False)(asset.content_location)
        else:
            raise ValueError(f"Content location is unset for asset {asset_id} for session {inputs.session_id}")

        if not video_bytes:
            raise ValueError(f"No video content found for asset {asset_id} for session {inputs.session_id}")

        duration = await sync_to_async(get_video_duration_s, thread_sensitive=False)(video_bytes)

        # Lazy so asset-check failures don't require an API key.
        raw_client = RawGenAIClient(api_key=settings.GEMINI_API_KEY)

        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.write(video_bytes)
            tmp_file.flush()
            logger.debug(
                f"Uploading full video to Gemini for session {inputs.session_id}",
                duration=duration,
                session_id=inputs.session_id,
                video_size_bytes=len(video_bytes),
                signals_type="session-summaries",
            )
            uploaded_file = await sync_to_async(raw_client.files.upload, thread_sensitive=False)(
                file=tmp_file.name,
                config=types.UploadFileConfig(mime_type=asset.export_format, display_name=workflow_id),
            )

        # Wrap both the missing-name guard and the track call in the same try so a Gemini
        # response without `.name` can't sneak past tracking and orphan a file.
        try:
            if uploaded_file.name is None:
                raise RuntimeError("Uploaded file has no name")
            await track_uploaded_file(uploaded_file.name, workflow_id, datetime.now(UTC))
        except Exception:
            logger.exception(
                "upload_video_to_gemini.track_failed_rolling_back",
                session_id=inputs.session_id,
                gemini_file_name=uploaded_file.name,
                signals_type="session-summaries",
            )
            if uploaded_file.name is not None:
                try:
                    await sync_to_async(raw_client.files.delete, thread_sensitive=False)(name=uploaded_file.name)
                except Exception:
                    logger.exception(
                        "upload_video_to_gemini.rollback_delete_failed",
                        session_id=inputs.session_id,
                        gemini_file_name=uploaded_file.name,
                        signals_type="session-summaries",
                    )
            raise

        gemini_file_name = uploaded_file.name
        assert gemini_file_name is not None  # narrowing for mypy; verified inside the try above

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
                file_name=gemini_file_name,
                file_state=uploaded_file.state.name,
                elapsed_seconds=elapsed,
                signals_type="session-summaries",
            )
            uploaded_file = await sync_to_async(raw_client.files.get, thread_sensitive=False)(name=gemini_file_name)

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
            gemini_file_name=gemini_file_name,
            mime_type=uploaded_file.mime_type or MOMENT_VIDEO_EXPORT_FORMAT,
            duration=duration,
        )
        inactivity_periods = asset.export_context.get("inactivity_periods") if asset.export_context else None
        return UploadVideoToGeminiOutput(
            uploaded_video=uploaded_video,
            inactivity_periods=(
                None
                if not inactivity_periods
                else [ReplayInactivityPeriod.model_validate(p) for p in inactivity_periods]
            ),
        )

    except Exception as e:
        logger.exception(
            f"Failed to upload video to Gemini for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        raise
