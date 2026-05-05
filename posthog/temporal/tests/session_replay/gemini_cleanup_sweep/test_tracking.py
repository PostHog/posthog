import json
import datetime as dt

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.temporal.session_replay.gemini_cleanup_sweep.constants import (
    REDIS_INDEX_KEY,
    REDIS_KEY_PREFIX,
    REDIS_KEY_TTL,
)
from posthog.temporal.session_replay.gemini_cleanup_sweep.tracking import (
    index_size,
    iter_tracked_files,
    track_uploaded_file,
    untrack_uploaded_file,
)
from posthog.temporal.session_replay.gemini_cleanup_sweep.types import TrackedFile

_NOW = dt.datetime(2026, 4, 24, 12, 0, 0, tzinfo=dt.UTC)


async def _collect(it) -> list[TrackedFile | None]:
    return [item async for item in it]


@pytest.mark.asyncio
async def test_track_writes_per_file_key_and_index_entry(gemini_redis):
    await track_uploaded_file("files/abc", "wf-1", _NOW)
    raw = await gemini_redis.get(f"{REDIS_KEY_PREFIX}files/abc")
    assert raw is not None
    payload = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    assert payload == {"workflow_id": "wf-1", "uploaded_at": _NOW.isoformat()}
    assert await gemini_redis.zscore(REDIS_INDEX_KEY, "files/abc") == _NOW.timestamp()
    ttl = await gemini_redis.ttl(f"{REDIS_KEY_PREFIX}files/abc")
    assert 0 < ttl <= int(REDIS_KEY_TTL.total_seconds())


@pytest.mark.asyncio
async def test_track_raises_when_redis_pipeline_fails(gemini_redis):
    failing_pipe = MagicMock()
    failing_pipe.set = MagicMock()
    failing_pipe.zadd = MagicMock()
    failing_pipe.execute = AsyncMock(side_effect=RuntimeError("redis down"))
    failing_pipe.__aenter__ = AsyncMock(return_value=failing_pipe)
    failing_pipe.__aexit__ = AsyncMock(return_value=None)

    fake_redis = MagicMock()
    fake_redis.pipeline = MagicMock(return_value=failing_pipe)
    with patch(
        "posthog.temporal.session_replay.gemini_cleanup_sweep.tracking.get_async_client",
        return_value=fake_redis,
    ):
        with pytest.raises(RuntimeError, match="redis down"):
            await track_uploaded_file("files/abc", "wf-1", _NOW)


@pytest.mark.asyncio
async def test_untrack_clears_per_file_key_and_index_entry(gemini_redis):
    await track_uploaded_file("files/abc", "wf-1", _NOW)
    await untrack_uploaded_file("files/abc")
    assert await gemini_redis.exists(f"{REDIS_KEY_PREFIX}files/abc") == 0
    assert await gemini_redis.zscore(REDIS_INDEX_KEY, "files/abc") is None


@pytest.mark.asyncio
async def test_untrack_swallows_redis_errors(gemini_redis):
    failing_pipe = MagicMock()
    failing_pipe.delete = MagicMock()
    failing_pipe.zrem = MagicMock()
    failing_pipe.execute = AsyncMock(side_effect=RuntimeError("redis down"))
    failing_pipe.__aenter__ = AsyncMock(return_value=failing_pipe)
    failing_pipe.__aexit__ = AsyncMock(return_value=None)

    fake_redis = MagicMock()
    fake_redis.pipeline = MagicMock(return_value=failing_pipe)
    with patch(
        "posthog.temporal.session_replay.gemini_cleanup_sweep.tracking.get_async_client",
        return_value=fake_redis,
    ):
        await untrack_uploaded_file("files/abc")


@pytest.mark.asyncio
async def test_iter_yields_tracked_files(gemini_redis):
    await track_uploaded_file("files/a", "wf-a", _NOW)
    await track_uploaded_file("files/b", "wf-b", _NOW - dt.timedelta(seconds=10))

    items = await _collect(iter_tracked_files(limit=10))
    by_name = {t.gemini_file_name: t for t in items if t is not None}
    assert set(by_name) == {"files/a", "files/b"}
    assert by_name["files/a"].workflow_id == "wf-a"
    assert by_name["files/a"].uploaded_at == _NOW
    assert by_name["files/b"].workflow_id == "wf-b"


@pytest.mark.asyncio
async def test_iter_yields_oldest_first(gemini_redis):
    await track_uploaded_file("files/new", "wf-new", _NOW)
    await track_uploaded_file("files/old", "wf-old", _NOW - dt.timedelta(hours=2))
    await track_uploaded_file("files/middle", "wf-middle", _NOW - dt.timedelta(minutes=30))

    items = await _collect(iter_tracked_files(limit=10))
    names = [t.gemini_file_name for t in items if t is not None]
    assert names == ["files/old", "files/middle", "files/new"]


@pytest.mark.parametrize(
    "value",
    [
        "not-json",  # JSONDecodeError
        '{"workflow_id": "wf-1"}',  # KeyError on uploaded_at
        '{"workflow_id": "wf-1", "uploaded_at": "garbage"}',  # ValueError from fromisoformat
    ],
)
@pytest.mark.asyncio
async def test_iter_yields_none_for_invalid_payload(gemini_redis, value):
    await gemini_redis.set(f"{REDIS_KEY_PREFIX}files/garbage", value)
    await gemini_redis.zadd(REDIS_INDEX_KEY, {"files/garbage": _NOW.timestamp()})
    items = await _collect(iter_tracked_files(limit=10))
    assert items == [None]


@pytest.mark.asyncio
async def test_iter_cleans_up_stale_index_entries(gemini_redis):
    await gemini_redis.zadd(REDIS_INDEX_KEY, {"files/stale": _NOW.timestamp()})
    items = await _collect(iter_tracked_files(limit=10))
    assert items == []
    assert await gemini_redis.zscore(REDIS_INDEX_KEY, "files/stale") is None


@pytest.mark.asyncio
async def test_iter_respects_limit(gemini_redis):
    for i in range(20):
        await track_uploaded_file(f"files/n{i}", "wf-x", _NOW + dt.timedelta(seconds=i))
    items = await _collect(iter_tracked_files(limit=5))
    assert len(items) == 5


@pytest.mark.asyncio
async def test_iter_batches_across_mget_boundary(gemini_redis):
    n = 250  # > MGET_BATCH_SIZE (200)
    for i in range(n):
        await track_uploaded_file(f"files/n{i:04d}", "wf-x", _NOW + dt.timedelta(seconds=i))
    items = await _collect(iter_tracked_files(limit=n))
    assert len({t.gemini_file_name for t in items if t is not None}) == n


@pytest.mark.asyncio
async def test_index_size_returns_index_cardinality(gemini_redis):
    assert await index_size() == 0
    await track_uploaded_file("files/a", "wf-a", _NOW)
    await track_uploaded_file("files/b", "wf-b", _NOW)
    assert await index_size() == 2
    await untrack_uploaded_file("files/a")
    assert await index_size() == 1
