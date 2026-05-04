import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

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
async def test_uploads_active_file_and_returns_reference():
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
