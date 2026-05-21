import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai.errors import ClientError, ServerError
from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.gemini_cleanup_sweep.constants import REDIS_INDEX_KEY, REDIS_KEY_PREFIX
from posthog.temporal.session_replay.session_summary.activities.video_based.a2_upload_video_to_gemini import (
    upload_video_to_gemini_activity,
)
from posthog.temporal.session_replay.session_summary.types.video import VideoSummarySingleSessionInputs

ACTIVITY_MODULE = "posthog.temporal.session_replay.session_summary.activities.video_based.a2_upload_video_to_gemini"


def _inputs() -> VideoSummarySingleSessionInputs:
    return VideoSummarySingleSessionInputs(
        session_id="sess-1",
        user_id=1,
        team_id=1,
        redis_key_base="test",
        model_to_use="test-model",
    )


def _make_uploaded_file(*, state: str = "ACTIVE", name: str = "files/abc", uri: str = "gs://x/y") -> MagicMock:
    f = MagicMock()
    f.state.name = state
    f.name = name
    f.uri = uri
    f.mime_type = "video/mp4"
    return f


def _make_asset(content: bytes | None = b"video", export_context: dict | None = None) -> MagicMock:
    asset = MagicMock()
    asset.content = content
    asset.content_location = None
    asset.export_format = "video/mp4"
    asset.export_context = export_context
    return asset


@pytest.mark.asyncio
async def test_uploads_active_file_and_writes_tracking(gemini_redis):
    asset = _make_asset(content=b"video-bytes")
    uploaded = _make_uploaded_file()
    fake_client = MagicMock()
    fake_client.files.upload.return_value = uploaded

    with (
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)),
        patch(f"{ACTIVITY_MODULE}.get_video_duration_s", return_value=42),
        patch(f"{ACTIVITY_MODULE}.RawGenAIClient", return_value=fake_client),
    ):
        result = await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)

    assert result["uploaded_video"].file_uri == "gs://x/y"
    assert result["uploaded_video"].gemini_file_name == "files/abc"
    assert result["uploaded_video"].duration == 42
    assert await gemini_redis.exists(f"{REDIS_KEY_PREFIX}files/abc") == 1
    assert await gemini_redis.zscore(REDIS_INDEX_KEY, "files/abc") is not None


@pytest.mark.asyncio
async def test_rolls_back_upload_when_tracking_fails(gemini_redis):
    asset = _make_asset(content=b"video-bytes")
    uploaded = _make_uploaded_file()
    fake_client = MagicMock()
    fake_client.files.upload.return_value = uploaded

    with (
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)),
        patch(f"{ACTIVITY_MODULE}.get_video_duration_s", return_value=42),
        patch(f"{ACTIVITY_MODULE}.RawGenAIClient", return_value=fake_client),
        patch(
            f"{ACTIVITY_MODULE}.track_uploaded_file",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ),
    ):
        with pytest.raises(RuntimeError, match="redis down"):
            await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)

    fake_client.files.delete.assert_called_once_with(name="files/abc")


@pytest.mark.asyncio
async def test_swallows_rollback_delete_failure(gemini_redis):
    asset = _make_asset(content=b"video-bytes")
    uploaded = _make_uploaded_file()
    fake_client = MagicMock()
    fake_client.files.upload.return_value = uploaded
    fake_client.files.delete.side_effect = RuntimeError("gemini down")

    with (
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)),
        patch(f"{ACTIVITY_MODULE}.get_video_duration_s", return_value=42),
        patch(f"{ACTIVITY_MODULE}.RawGenAIClient", return_value=fake_client),
        patch(
            f"{ACTIVITY_MODULE}.track_uploaded_file",
            new=AsyncMock(side_effect=RuntimeError("redis down")),
        ),
    ):
        with pytest.raises(RuntimeError, match="redis down"):
            await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)

    fake_client.files.delete.assert_called_once_with(name="files/abc")


@pytest.mark.asyncio
async def test_raises_when_asset_has_no_content():
    asset = _make_asset(content=None)

    with patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)):
        with pytest.raises(ValueError, match="Content location is unset"):
            await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)


@pytest.mark.asyncio
async def test_raises_when_gemini_processing_fails():
    asset = _make_asset(content=b"video-bytes")
    failed = _make_uploaded_file(state="FAILED")
    fake_client = MagicMock()
    fake_client.files.upload.return_value = failed

    with (
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)),
        patch(f"{ACTIVITY_MODULE}.get_video_duration_s", return_value=42),
        patch(f"{ACTIVITY_MODULE}.RawGenAIClient", return_value=fake_client),
    ):
        with pytest.raises(RuntimeError, match="File processing failed"):
            await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)


@pytest.mark.parametrize(
    "raised, expected_match",
    [
        (
            ValueError("Failed to upload file: Upload status is not finalized."),
            r"files\.upload failed.*ValueError",
        ),
        (
            ClientError(code=400, response_json={"error": {"code": 400, "message": "bad arg"}}),
            r"files\.upload failed.*ClientError",
        ),
        (
            ServerError(code=502, response_json={"error": {"code": 502, "message": "bad gateway"}}),
            r"files\.upload failed.*ServerError",
        ),
    ],
)
@pytest.mark.asyncio
async def test_translates_upload_failures(gemini_redis, raised, expected_match):
    """SDK upload failures (bare ValueError + APIError subclasses) used to leak through as raw SDK
    messages and silently disappear in the UI. They now translate into RuntimeError with session
    context so Temporal retries see a clean cause and the workflow's error path can surface to the
    frontend banner."""
    asset = _make_asset(content=b"video-bytes")
    fake_client = MagicMock()
    fake_client.files.upload.side_effect = raised

    with (
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)),
        patch(f"{ACTIVITY_MODULE}.get_video_duration_s", return_value=42),
        patch(f"{ACTIVITY_MODULE}.RawGenAIClient", return_value=fake_client),
    ):
        with pytest.raises(RuntimeError, match=expected_match) as excinfo:
            await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)

    assert excinfo.value.__cause__ is raised


@pytest.mark.asyncio
async def test_polling_get_client_error_is_translated(gemini_redis):
    """A 400 from files.get during PROCESSING polling used to surface as a raw SDK ClientError.
    Wrap it so Temporal sees a session-scoped RuntimeError with the SDK error as __cause__."""
    asset = _make_asset(content=b"video-bytes")
    processing = _make_uploaded_file(state="PROCESSING")
    fake_client = MagicMock()
    fake_client.files.upload.return_value = processing
    sdk_err = ClientError(code=400, response_json={"error": {"code": 400, "message": "Request contains an invalid argument."}})
    fake_client.files.get.side_effect = sdk_err

    with (
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)),
        patch(f"{ACTIVITY_MODULE}.get_video_duration_s", return_value=42),
        patch(f"{ACTIVITY_MODULE}.RawGenAIClient", return_value=fake_client),
        patch(f"{ACTIVITY_MODULE}.asyncio.sleep", new=AsyncMock(return_value=None)),
    ):
        with pytest.raises(RuntimeError, match=r"files\.get failed during PROCESSING poll") as excinfo:
            await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)

    assert excinfo.value.__cause__ is sdk_err


@pytest.mark.asyncio
async def test_polling_get_server_error_is_translated(gemini_redis):
    asset = _make_asset(content=b"video-bytes")
    processing = _make_uploaded_file(state="PROCESSING")
    fake_client = MagicMock()
    fake_client.files.upload.return_value = processing
    sdk_err = ServerError(code=503, response_json={"error": {"code": 503, "message": "service unavailable"}})
    fake_client.files.get.side_effect = sdk_err

    with (
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)),
        patch(f"{ACTIVITY_MODULE}.get_video_duration_s", return_value=42),
        patch(f"{ACTIVITY_MODULE}.RawGenAIClient", return_value=fake_client),
        patch(f"{ACTIVITY_MODULE}.asyncio.sleep", new=AsyncMock(return_value=None)),
    ):
        with pytest.raises(RuntimeError, match=r"files\.get hit a server error") as excinfo:
            await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)

    assert excinfo.value.__cause__ is sdk_err


@pytest.mark.asyncio
async def test_polling_get_enforces_timeout_including_inflight_latency(gemini_redis):
    """The previous loop checked elapsed only at the top of each iteration, so a slow files.get
    could push total elapsed well past MAX_PROCESSING_WAIT_SECONDS (observed 387.9s vs 300s). Now
    the call is wrapped in asyncio.wait_for so an unresponsive files.get is cut off within budget."""
    asset = _make_asset(content=b"video-bytes")
    processing = _make_uploaded_file(state="PROCESSING")
    fake_client = MagicMock()
    fake_client.files.upload.return_value = processing
    # Sync sleep > MAX_PROCESSING_WAIT_SECONDS to simulate a stalled files.get inside the thread.
    fake_client.files.get.side_effect = lambda **_kwargs: time.sleep(0.5)

    with (
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.aget", new=AsyncMock(return_value=asset)),
        patch(f"{ACTIVITY_MODULE}.get_video_duration_s", return_value=42),
        patch(f"{ACTIVITY_MODULE}.RawGenAIClient", return_value=fake_client),
        patch(f"{ACTIVITY_MODULE}.asyncio.sleep", new=AsyncMock(return_value=None)),
        patch(f"{ACTIVITY_MODULE}.MAX_PROCESSING_WAIT_SECONDS", 0.05),
    ):
        with pytest.raises(RuntimeError, match=r"timed out"):
            await ActivityEnvironment().run(upload_video_to_gemini_activity, _inputs(), 99)
