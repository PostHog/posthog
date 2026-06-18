import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.session_summary.activities.video_based.a1_prep_session_video_asset import (
    prep_session_video_asset_activity,
)
from posthog.temporal.session_replay.session_summary.types.video import VideoSummarySingleSessionInputs

ACTIVITY_MODULE = "posthog.temporal.session_replay.session_summary.activities.video_based.a1_prep_session_video_asset"


def _inputs() -> VideoSummarySingleSessionInputs:
    return VideoSummarySingleSessionInputs(
        session_id="sess-1",
        user_id=1,
        team_id=1,
        redis_key_base="test",
        model_to_use="test-model",
    )


@pytest.mark.asyncio
async def test_returns_none_when_summary_already_exists():
    with patch(f"{ACTIVITY_MODULE}.SingleSessionSummary.objects.get_summary", return_value=MagicMock()):
        result = await ActivityEnvironment().run(prep_session_video_asset_activity, _inputs())
    assert result is None


@pytest.mark.asyncio
async def test_raises_when_metadata_missing():
    with (
        patch(f"{ACTIVITY_MODULE}.SingleSessionSummary.objects.get_summary", return_value=None),
        patch(f"{ACTIVITY_MODULE}.Team.objects.aget", new=AsyncMock(return_value=MagicMock())),
        patch(f"{ACTIVITY_MODULE}.SessionReplayEvents") as mock_sre,
    ):
        mock_sre.return_value.get_metadata.return_value = None
        with pytest.raises(ValueError, match="No metadata found"):
            await ActivityEnvironment().run(prep_session_video_asset_activity, _inputs())


@pytest.mark.asyncio
async def test_returns_none_when_session_too_short():
    with (
        patch(f"{ACTIVITY_MODULE}.SingleSessionSummary.objects.get_summary", return_value=None),
        patch(f"{ACTIVITY_MODULE}.Team.objects.aget", new=AsyncMock(return_value=MagicMock())),
        patch(f"{ACTIVITY_MODULE}.SessionReplayEvents") as mock_sre,
    ):
        # Below MIN_SESSION_DURATION_FOR_VIDEO_SUMMARY_S
        mock_sre.return_value.get_metadata.return_value = {"duration": 1}
        result = await ActivityEnvironment().run(prep_session_video_asset_activity, _inputs())
    assert result is None


@pytest.mark.asyncio
async def test_existing_asset_lookup_is_scoped_to_system_assets():
    captured_filter_kwargs: dict = {}

    def _capture_filter(**kwargs):
        captured_filter_kwargs.update(kwargs)
        qs = MagicMock()
        qs.afirst = AsyncMock(return_value=None)
        return qs

    team = MagicMock(api_token="tok")
    team.name = "Test Team"
    with (
        patch(f"{ACTIVITY_MODULE}.SingleSessionSummary.objects.get_summary", return_value=None),
        patch(f"{ACTIVITY_MODULE}.Team.objects.aget", new=AsyncMock(return_value=team)),
        patch(f"{ACTIVITY_MODULE}.SessionReplayEvents") as mock_sre,
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.filter", side_effect=_capture_filter),
        patch(f"{ACTIVITY_MODULE}.ExportedAsset.objects.acreate", new=AsyncMock(return_value=MagicMock(id=99))),
    ):
        mock_sre.return_value.get_metadata.return_value = {"duration": 999}
        await ActivityEnvironment().run(prep_session_video_asset_activity, _inputs())

    assert captured_filter_kwargs.get("is_system") is True
