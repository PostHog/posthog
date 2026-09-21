import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import (
    _KILLED_WORKER_TTL_SECONDS,
    _STUCK_TTL_SECONDS,
    STUCK_SESSION_THRESHOLD,
    BumpStuckCounterInput,
    bump_stuck_counter_activity,
    read_stuck_session_ids,
)


@parameterized.expand(
    [
        # (killed_worker, remaining_ttl, expected_amount, expected_ttl)
        (False, -2, 1, _STUCK_TTL_SECONDS),
        (True, -2, STUCK_SESSION_THRESHOLD, _KILLED_WORKER_TTL_SECONDS),
        # An ordinary bump inside a killed-worker quarantine must not downgrade the longer TTL.
        (False, _KILLED_WORKER_TTL_SECONDS - 60, 1, _KILLED_WORKER_TTL_SECONDS - 60),
    ]
)
@pytest.mark.asyncio
async def test_bump_stuck_counter_pipelines_incrby_and_expire(
    killed_worker, remaining_ttl, expected_amount, expected_ttl
):
    redis_client = MagicMock()
    redis_client.ttl = AsyncMock(return_value=remaining_ttl)
    pipeline = MagicMock()
    pipeline.incrby = MagicMock()
    pipeline.expire = MagicMock()
    pipeline.execute = AsyncMock(return_value=[1, True])
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock(return_value=False)
    redis_client.pipeline = MagicMock(return_value=pipeline)

    with patch(
        "posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter.get_async_client",
        return_value=redis_client,
    ):
        await bump_stuck_counter_activity(
            BumpStuckCounterInput(team_id=42, session_id="abc", killed_worker=killed_worker)
        )

    pipeline.incrby.assert_called_once_with("replay:rasterize:stuck:42:abc", expected_amount)
    pipeline.expire.assert_called_once_with("replay:rasterize:stuck:42:abc", expected_ttl)
    pipeline.execute.assert_awaited_once()


def _patched_client(mget_result=None, side_effect=None):
    redis_client = MagicMock()
    redis_client.mget = MagicMock(return_value=mget_result, side_effect=side_effect)
    return patch(
        "posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter.get_client",
        return_value=redis_client,
    ), redis_client


def test_read_stuck_returns_empty_for_empty_input():
    patcher, _ = _patched_client(side_effect=AssertionError("should not mget empty input"))
    with patcher:
        assert read_stuck_session_ids(team_id=1, session_ids=[], threshold=3) == set()


def test_read_stuck_thresholds_correctly():
    patcher, _ = _patched_client(mget_result=[b"3", b"2", b"5", None])
    with patcher:
        result = read_stuck_session_ids(team_id=42, session_ids=["s1", "s2", "s3", "s4"], threshold=3)
    assert result == {"s1", "s3"}


def test_read_stuck_skips_non_integer_values():
    patcher, _ = _patched_client(mget_result=[b"not-an-int", b"5"])
    with patcher:
        result = read_stuck_session_ids(team_id=42, session_ids=["s1", "s2"], threshold=3)
    assert result == {"s2"}


def test_read_stuck_uses_team_scoped_keys():
    patcher, redis_client = _patched_client(mget_result=[None, None])
    with patcher:
        read_stuck_session_ids(team_id=42, session_ids=["s1", "s2"], threshold=3)
    redis_client.mget.assert_called_once_with(["replay:rasterize:stuck:42:s1", "replay:rasterize:stuck:42:s2"])
