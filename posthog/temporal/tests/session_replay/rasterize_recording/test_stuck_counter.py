import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import (
    _STUCK_TTL_SECONDS,
    BumpStuckCounterInput,
    bump_stuck_counter_activity,
    read_stuck_session_ids,
)


@pytest.mark.asyncio
async def test_bump_stuck_counter_pipelines_incr_and_expire():
    redis_client = MagicMock()
    pipeline = MagicMock()
    pipeline.incr = MagicMock()
    pipeline.expire = MagicMock()
    pipeline.execute = AsyncMock(return_value=[1, True])
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock(return_value=False)
    redis_client.pipeline = MagicMock(return_value=pipeline)

    with patch(
        "posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter.get_async_client",
        return_value=redis_client,
    ):
        await bump_stuck_counter_activity(BumpStuckCounterInput(team_id=42, session_id="abc"))

    pipeline.incr.assert_called_once_with("replay:rasterize:stuck:42:abc")
    pipeline.expire.assert_called_once_with("replay:rasterize:stuck:42:abc", _STUCK_TTL_SECONDS)
    pipeline.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_read_stuck_returns_empty_for_empty_input():
    redis_client = MagicMock()
    redis_client.mget = AsyncMock(side_effect=AssertionError("should not call mget for empty input"))
    result = await read_stuck_session_ids(redis_client, team_id=1, session_ids=[], threshold=3)
    assert result == set()


@pytest.mark.asyncio
async def test_read_stuck_thresholds_correctly():
    redis_client = MagicMock()
    redis_client.mget = AsyncMock(return_value=[b"3", b"2", b"5", None])

    result = await read_stuck_session_ids(
        redis_client,
        team_id=42,
        session_ids=["s1", "s2", "s3", "s4"],
        threshold=3,
    )
    # s1 == threshold (stuck), s2 below (not stuck), s3 above (stuck), s4 None (not stuck)
    assert result == {"s1", "s3"}


@pytest.mark.asyncio
async def test_read_stuck_skips_non_integer_values():
    redis_client = MagicMock()
    redis_client.mget = AsyncMock(return_value=[b"not-an-int", b"5"])
    result = await read_stuck_session_ids(
        redis_client,
        team_id=42,
        session_ids=["bad", "good"],
        threshold=3,
    )
    assert result == {"good"}


@pytest.mark.asyncio
async def test_read_stuck_uses_team_scoped_keys():
    redis_client = MagicMock()
    captured_keys: list[str] = []

    async def _mget(keys):
        captured_keys.extend(keys)
        return [None] * len(keys)

    redis_client.mget = _mget
    await read_stuck_session_ids(redis_client, team_id=42, session_ids=["s1", "s2"], threshold=3)
    assert captured_keys == ["replay:rasterize:stuck:42:s1", "replay:rasterize:stuck:42:s2"]
