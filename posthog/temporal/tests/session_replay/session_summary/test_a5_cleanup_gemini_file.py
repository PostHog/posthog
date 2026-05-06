import pytest
from unittest.mock import MagicMock, patch

from temporalio.testing import ActivityEnvironment

from posthog.temporal.session_replay.gemini_cleanup_sweep.constants import REDIS_INDEX_KEY, REDIS_KEY_PREFIX
from posthog.temporal.session_replay.session_summary.activities.video_based.a5_cleanup_gemini_file import (
    cleanup_gemini_file_activity,
)


@pytest.mark.asyncio
async def test_deletes_file_via_gemini_client_and_clears_tracking(gemini_redis):
    await gemini_redis.set(f"{REDIS_KEY_PREFIX}files/abc123", "{}")
    await gemini_redis.zadd(REDIS_INDEX_KEY, {"files/abc123": 0.0})
    fake_client = MagicMock()
    with patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a5_cleanup_gemini_file.RawGenAIClient",
        return_value=fake_client,
    ):
        await ActivityEnvironment().run(cleanup_gemini_file_activity, "files/abc123", "session-1")

    fake_client.files.delete.assert_called_once_with(name="files/abc123")
    assert await gemini_redis.exists(f"{REDIS_KEY_PREFIX}files/abc123") == 0
    assert await gemini_redis.zscore(REDIS_INDEX_KEY, "files/abc123") is None


@pytest.mark.asyncio
async def test_keeps_tracking_when_gemini_delete_fails(gemini_redis):
    await gemini_redis.set(f"{REDIS_KEY_PREFIX}files/abc123", "{}")
    await gemini_redis.zadd(REDIS_INDEX_KEY, {"files/abc123": 0.0})
    fake_client = MagicMock()
    fake_client.files.delete.side_effect = RuntimeError("gemini down")
    with patch(
        "posthog.temporal.session_replay.session_summary.activities.video_based.a5_cleanup_gemini_file.RawGenAIClient",
        return_value=fake_client,
    ):
        await ActivityEnvironment().run(cleanup_gemini_file_activity, "files/abc123", "session-1")

    assert await gemini_redis.exists(f"{REDIS_KEY_PREFIX}files/abc123") == 1
    assert await gemini_redis.zscore(REDIS_INDEX_KEY, "files/abc123") is not None
