import json
import datetime as dt
from dataclasses import dataclass

import pytest
from unittest.mock import AsyncMock, patch

from google.genai.errors import APIError
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.session_replay.gemini_cleanup_sweep.activities import sweep_gemini_files_activity
from posthog.temporal.session_replay.gemini_cleanup_sweep.constants import (
    MAX_FILES_PER_SWEEP,
    REDIS_INDEX_KEY,
    REDIS_KEY_PREFIX,
    REDIS_KEY_TTL,
    SWEEP_MIN_AGE,
)
from posthog.temporal.session_replay.gemini_cleanup_sweep.types import CleanupSweepInputs, CleanupSweepResult

_NOW = dt.datetime(2026, 4, 24, 12, 0, 0, tzinfo=dt.UTC)


@dataclass
class _Outcome:
    status: WorkflowExecutionStatus | None = None
    raise_not_found: bool = False
    raise_rpc_error: bool = False


class _StubHandle:
    def __init__(self, outcome: _Outcome) -> None:
        self._outcome = outcome

    async def describe(self):
        if self._outcome.raise_not_found:
            raise RPCError("not found", RPCStatusCode.NOT_FOUND, b"")
        if self._outcome.raise_rpc_error:
            raise RPCError("boom", RPCStatusCode.INTERNAL, b"")

        class _Desc:
            status = self._outcome.status

        return _Desc()


class _StubTemporal:
    def __init__(self, outcomes: dict[str, _Outcome]) -> None:
        self._outcomes = outcomes

    def get_workflow_handle(self, workflow_id: str) -> _StubHandle:
        return _StubHandle(self._outcomes.get(workflow_id, _Outcome(status=WorkflowExecutionStatus.RUNNING)))


class _StubFiles:
    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.delete_raises_for: dict[str, BaseException] = {}

    def delete(self, *, name: str) -> None:
        if name in self.delete_raises_for:
            raise self.delete_raises_for[name]
        self.deleted.append(name)


class _StubRawClient:
    def __init__(self) -> None:
        self.files = _StubFiles()


@pytest.fixture
def fixed_now():
    class _FixedDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _NOW if tz is None else _NOW.astimezone(tz)

    with patch(
        "posthog.temporal.session_replay.gemini_cleanup_sweep.activities.datetime",
        _FixedDatetime,
    ):
        yield


async def _track(client, *, file_name: str, workflow_id: str, age: dt.timedelta) -> None:
    uploaded_at = _NOW - age
    payload = json.dumps({"workflow_id": workflow_id, "uploaded_at": uploaded_at.isoformat()})
    await client.set(f"{REDIS_KEY_PREFIX}{file_name}", payload, ex=int(REDIS_KEY_TTL.total_seconds()))
    await client.zadd(REDIS_INDEX_KEY, {file_name: uploaded_at.timestamp()})


def _patch_clients(raw_client: _StubRawClient, temporal: _StubTemporal):
    return (
        patch(
            "posthog.temporal.session_replay.gemini_cleanup_sweep.activities.RawGenAIClient",
            return_value=raw_client,
        ),
        patch(
            "posthog.temporal.session_replay.gemini_cleanup_sweep.activities.async_connect",
            new=AsyncMock(return_value=temporal),
        ),
    )


async def _key_exists(client, file_name: str) -> bool:
    return bool(await client.exists(f"{REDIS_KEY_PREFIX}{file_name}"))


async def _index_has(client, file_name: str) -> bool:
    return await client.zscore(REDIS_INDEX_KEY, file_name) is not None


@pytest.mark.asyncio
async def test_no_keys_returns_zeros(activity_environment, fixed_now, gemini_redis):
    raw, tmp = _StubRawClient(), _StubTemporal({})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result == CleanupSweepResult()
    assert raw.files.deleted == []


@pytest.mark.asyncio
async def test_skips_keys_younger_than_min_age(activity_environment, fixed_now, gemini_redis):
    await _track(gemini_redis, file_name="files/young", workflow_id="wf-1", age=SWEEP_MIN_AGE / 2)
    raw, tmp = _StubRawClient(), _StubTemporal({"wf-1": _Outcome(status=WorkflowExecutionStatus.COMPLETED)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.scanned == 1
    assert result.skipped_too_young == 1
    assert result.deleted == 0
    assert raw.files.deleted == []
    assert await _key_exists(gemini_redis, "files/young")
    assert await _index_has(gemini_redis, "files/young")


@pytest.mark.parametrize(
    "status",
    [
        WorkflowExecutionStatus.COMPLETED,
        WorkflowExecutionStatus.FAILED,
        WorkflowExecutionStatus.CANCELED,
        WorkflowExecutionStatus.TERMINATED,
        WorkflowExecutionStatus.TIMED_OUT,
    ],
)
@pytest.mark.asyncio
async def test_deletes_files_for_terminal_workflows(activity_environment, fixed_now, gemini_redis, status):
    await _track(gemini_redis, file_name="files/old", workflow_id="wf-1", age=SWEEP_MIN_AGE * 10)
    raw, tmp = _StubRawClient(), _StubTemporal({"wf-1": _Outcome(status=status)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.deleted == 1
    assert raw.files.deleted == ["files/old"]
    assert not await _key_exists(gemini_redis, "files/old")
    assert not await _index_has(gemini_redis, "files/old")


@pytest.mark.parametrize(
    "status",
    [WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CONTINUED_AS_NEW],
)
@pytest.mark.asyncio
async def test_skips_files_for_active_workflows(activity_environment, fixed_now, gemini_redis, status):
    await _track(gemini_redis, file_name="files/in-use", workflow_id="wf-1", age=SWEEP_MIN_AGE * 10)
    raw, tmp = _StubRawClient(), _StubTemporal({"wf-1": _Outcome(status=status)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_running == 1
    assert result.deleted == 0
    assert raw.files.deleted == []
    assert await _key_exists(gemini_redis, "files/in-use")
    assert await _index_has(gemini_redis, "files/in-use")


@pytest.mark.asyncio
async def test_status_none_is_treated_as_running(activity_environment, fixed_now, gemini_redis):
    await _track(gemini_redis, file_name="files/maybe-running", workflow_id="wf-1", age=SWEEP_MIN_AGE * 10)
    raw, tmp = _StubRawClient(), _StubTemporal({"wf-1": _Outcome(status=None)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_running == 1
    assert result.deleted == 0


@pytest.mark.asyncio
async def test_deletes_when_workflow_not_found(activity_environment, fixed_now, gemini_redis):
    await _track(gemini_redis, file_name="files/orphan", workflow_id="wf-1", age=SWEEP_MIN_AGE * 10)
    raw, tmp = _StubRawClient(), _StubTemporal({"wf-1": _Outcome(raise_not_found=True)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.deleted == 1
    assert raw.files.deleted == ["files/orphan"]
    assert not await _key_exists(gemini_redis, "files/orphan")
    assert not await _index_has(gemini_redis, "files/orphan")


@pytest.mark.asyncio
async def test_skips_on_temporal_rpc_error(activity_environment, fixed_now, gemini_redis):
    await _track(gemini_redis, file_name="files/unknown", workflow_id="wf-1", age=SWEEP_MIN_AGE * 10)
    raw, tmp = _StubRawClient(), _StubTemporal({"wf-1": _Outcome(raise_rpc_error=True)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_temporal_error == 1
    assert result.deleted == 0
    assert await _key_exists(gemini_redis, "files/unknown")
    assert await _index_has(gemini_redis, "files/unknown")


@pytest.mark.asyncio
async def test_delete_failure_keeps_redis_state_for_retry(activity_environment, fixed_now, gemini_redis):
    await _track(gemini_redis, file_name="files/ok", workflow_id="wf-1", age=SWEEP_MIN_AGE * 10)
    await _track(gemini_redis, file_name="files/bad", workflow_id="wf-2", age=SWEEP_MIN_AGE * 10)
    raw = _StubRawClient()
    raw.files.delete_raises_for = {"files/bad": RuntimeError("simulated")}
    tmp = _StubTemporal(
        {
            "wf-1": _Outcome(status=WorkflowExecutionStatus.COMPLETED),
            "wf-2": _Outcome(status=WorkflowExecutionStatus.COMPLETED),
        }
    )
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.deleted == 1
    assert result.delete_failed == 1
    assert raw.files.deleted == ["files/ok"]
    assert not await _key_exists(gemini_redis, "files/ok")
    assert not await _index_has(gemini_redis, "files/ok")
    assert await _key_exists(gemini_redis, "files/bad")
    assert await _index_has(gemini_redis, "files/bad")


@pytest.mark.asyncio
async def test_treats_gemini_404_as_success(activity_environment, fixed_now, gemini_redis):
    # If a previous untrack failed and left an orphan key, the actual file may already be gone
    # from Gemini. Don't keep retrying — drop the key and move on.
    await _track(gemini_redis, file_name="files/already-gone", workflow_id="wf-1", age=SWEEP_MIN_AGE * 10)
    raw = _StubRawClient()
    raw.files.delete_raises_for = {"files/already-gone": APIError(code=404, response_json={})}
    tmp = _StubTemporal({"wf-1": _Outcome(status=WorkflowExecutionStatus.COMPLETED)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.deleted == 1
    assert result.delete_failed == 0
    assert not await _key_exists(gemini_redis, "files/already-gone")
    assert not await _index_has(gemini_redis, "files/already-gone")


@pytest.mark.asyncio
async def test_invalid_value_counted_separately(activity_environment, fixed_now, gemini_redis):
    await gemini_redis.set(f"{REDIS_KEY_PREFIX}files/garbage", "not-json")
    await gemini_redis.zadd(REDIS_INDEX_KEY, {"files/garbage": _NOW.timestamp()})
    raw, tmp = _StubRawClient(), _StubTemporal({})

    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_invalid_value == 1
    assert result.deleted == 0


@pytest.mark.asyncio
async def test_stale_index_entries_are_cleaned_up(activity_environment, fixed_now, gemini_redis):
    await gemini_redis.zadd(REDIS_INDEX_KEY, {"files/stale": _NOW.timestamp()})
    raw, tmp = _StubRawClient(), _StubTemporal({})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.scanned == 0
    assert result.deleted == 0
    assert not await _index_has(gemini_redis, "files/stale")


@pytest.mark.asyncio
async def test_hit_max_files_cap_set_when_index_exceeds_limit(activity_environment, fixed_now, gemini_redis):
    extras = MAX_FILES_PER_SWEEP + 1
    uploaded_at = _NOW - SWEEP_MIN_AGE * 10
    pipe = gemini_redis.pipeline()
    for i in range(extras):
        fn = f"files/n{i}"
        pipe.set(
            f"{REDIS_KEY_PREFIX}{fn}",
            json.dumps({"workflow_id": "wf-x", "uploaded_at": uploaded_at.isoformat()}),
            ex=int(REDIS_KEY_TTL.total_seconds()),
        )
        pipe.zadd(REDIS_INDEX_KEY, {fn: uploaded_at.timestamp()})
    await pipe.execute()
    raw, tmp = _StubRawClient(), _StubTemporal({"wf-x": _Outcome(raise_not_found=True)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.hit_max_files_cap is True
    assert result.scanned == MAX_FILES_PER_SWEEP
    assert result.deleted == MAX_FILES_PER_SWEEP


@pytest.mark.asyncio
async def test_mixed_cycle_aggregates_correctly(activity_environment, fixed_now, gemini_redis):
    await _track(gemini_redis, file_name="files/young", workflow_id="wf-young", age=SWEEP_MIN_AGE / 2)
    await _track(gemini_redis, file_name="files/done", workflow_id="wf-done", age=SWEEP_MIN_AGE * 10)
    await _track(gemini_redis, file_name="files/running", workflow_id="wf-run", age=SWEEP_MIN_AGE * 10)
    await _track(gemini_redis, file_name="files/orphan", workflow_id="wf-orphan", age=SWEEP_MIN_AGE * 10)
    await _track(gemini_redis, file_name="files/error", workflow_id="wf-err", age=SWEEP_MIN_AGE * 10)
    await gemini_redis.set(f"{REDIS_KEY_PREFIX}files/garbage", "not-json")
    await gemini_redis.zadd(REDIS_INDEX_KEY, {"files/garbage": _NOW.timestamp()})
    raw = _StubRawClient()
    tmp = _StubTemporal(
        {
            "wf-done": _Outcome(status=WorkflowExecutionStatus.COMPLETED),
            "wf-run": _Outcome(status=WorkflowExecutionStatus.RUNNING),
            "wf-orphan": _Outcome(raise_not_found=True),
            "wf-err": _Outcome(raise_rpc_error=True),
        }
    )
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.scanned == 6
    assert result.skipped_too_young == 1
    assert result.skipped_running == 1
    assert result.skipped_temporal_error == 1
    assert result.skipped_invalid_value == 1
    assert result.deleted == 2
    assert sorted(raw.files.deleted) == ["files/done", "files/orphan"]
