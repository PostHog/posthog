import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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
