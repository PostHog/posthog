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
    # The activity guards against re-running when a summary lands between the
    # workflow-entry check and this point.
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
