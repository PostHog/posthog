from datetime import datetime

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.session_summary.activities.video_based.a6a_embed_and_store_segments import (
    embed_and_store_segments_activity,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    VideoSegmentOutput,
    VideoSummarySingleSessionInputs,
)

ACTIVITY_MODULE = "posthog.temporal.session_replay.session_summary.activities.video_based.a6a_embed_and_store_segments"


def _inputs() -> VideoSummarySingleSessionInputs:
    return VideoSummarySingleSessionInputs(
        session_id="sess-1",
        user_id=1,
        team_id=42,
        redis_key_base="test",
        model_to_use="test-model",
    )


def _segments() -> list[VideoSegmentOutput]:
    return [
        VideoSegmentOutput(start_time="00:00", end_time="00:30", description="Login flow"),
        VideoSegmentOutput(start_time="00:30", end_time="01:00", description="Dashboard browsing"),
    ]


def _metadata() -> dict:
    return {
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "end_time": datetime(2024, 1, 1, 12, 1, 0),
        "duration": 60,
        "active_seconds": 50,
    }


@pytest.mark.asyncio
async def test_emits_one_embedding_request_per_segment():
    emit_mock = MagicMock()
    with (
        patch(f"{ACTIVITY_MODULE}.Team.objects.aget", new=AsyncMock(return_value=MagicMock())),
        patch(f"{ACTIVITY_MODULE}.SessionReplayEvents") as mock_sre,
        patch(f"{ACTIVITY_MODULE}.emit_embedding_request", new=emit_mock),
    ):
        mock_sre.return_value.get_metadata.return_value = _metadata()
        await ActivityEnvironment().run(embed_and_store_segments_activity, _inputs(), _segments())

    assert emit_mock.call_count == 2
    first_kwargs = emit_mock.call_args_list[0].kwargs
    assert first_kwargs["team_id"] == 42
    assert first_kwargs["document_id"] == "sess-1:00:00:00:30"
    assert first_kwargs["content"] == "Login flow"


@pytest.mark.asyncio
async def test_returns_early_when_metadata_missing():
    emit_mock = MagicMock()
    with (
        patch(f"{ACTIVITY_MODULE}.Team.objects.aget", new=AsyncMock(return_value=MagicMock())),
        patch(f"{ACTIVITY_MODULE}.SessionReplayEvents") as mock_sre,
        patch(f"{ACTIVITY_MODULE}.emit_embedding_request", new=emit_mock),
    ):
        mock_sre.return_value.get_metadata.return_value = None
        await ActivityEnvironment().run(embed_and_store_segments_activity, _inputs(), _segments())

    emit_mock.assert_not_called()


@pytest.mark.asyncio
async def test_raises_when_emit_fails():
    # If kafka producer fails the activity raises so Temporal can retry the whole batch.
    emit_mock = MagicMock(side_effect=RuntimeError("kafka down"))
    with (
        patch(f"{ACTIVITY_MODULE}.Team.objects.aget", new=AsyncMock(return_value=MagicMock())),
        patch(f"{ACTIVITY_MODULE}.SessionReplayEvents") as mock_sre,
        patch(f"{ACTIVITY_MODULE}.emit_embedding_request", new=emit_mock),
    ):
        mock_sre.return_value.get_metadata.return_value = _metadata()
        with pytest.raises(RuntimeError, match="kafka down"):
            await ActivityEnvironment().run(embed_and_store_segments_activity, _inputs(), _segments())
