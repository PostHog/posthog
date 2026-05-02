import datetime as dt
from dataclasses import dataclass

import pytest
from unittest.mock import AsyncMock, patch

from google.genai import types
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.session_replay.gemini_cleanup_sweep.activities import sweep_gemini_files_activity
from posthog.temporal.session_replay.gemini_cleanup_sweep.constants import AGE_THRESHOLD, MAX_FILES_PER_SWEEP
from posthog.temporal.session_replay.gemini_cleanup_sweep.types import CleanupSweepInputs, CleanupSweepResult

_NOW = dt.datetime(2026, 4, 24, 12, 0, 0, tzinfo=dt.UTC)
_DEPLOYMENT = "TEST"


@pytest.fixture(autouse=True)
def _set_deployment(settings):
    settings.CLOUD_DEPLOYMENT = _DEPLOYMENT


def _file(
    *,
    name: str,
    display_name: str | None,
    age: dt.timedelta,
) -> types.File:
    return types.File(name=name, display_name=display_name, create_time=_NOW - age)


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
    def __init__(self, files: list[types.File]) -> None:
        self._files = files
        self.deleted: list[str] = []
        self.delete_raises_for: set[str] = set()

    def list(self, *, config=None):
        return iter(self._files)

    def delete(self, *, name: str) -> None:
        if name in self.delete_raises_for:
            raise RuntimeError(f"simulated delete failure for {name}")
        self.deleted.append(name)


class _StubRawClient:
    def __init__(self, files: list[types.File]) -> None:
        self.files = _StubFiles(files)


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


def _wid(team_id: int, session_id: str) -> str:
    """Temporal workflow id (matches `SummarizeSingleSessionWorkflow.workflow_id_for`)."""
    return f"session-summary:single:{team_id}:{session_id}"


def _dn(team_id: int, session_id: str) -> str:
    """Display-name a real upload would write: deployment-prefixed workflow id."""
    return f"{_DEPLOYMENT}:{_wid(team_id, session_id)}"


@pytest.mark.asyncio
async def test_empty_pager_returns_zeros(activity_environment, fixed_now):
    raw, tmp = _StubRawClient([]), _StubTemporal({})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result == CleanupSweepResult()
    assert raw.files.deleted == []


@pytest.mark.asyncio
async def test_skips_files_younger_than_threshold(activity_environment, fixed_now):
    f = _file(name="files/young", display_name=_dn(1, "s1"), age=AGE_THRESHOLD - dt.timedelta(minutes=1))
    raw, tmp = _StubRawClient([f]), _StubTemporal({_wid(1, "s1"): _Outcome(status=WorkflowExecutionStatus.COMPLETED)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_too_young == 1
    assert result.deleted == 0
    assert raw.files.deleted == []


@pytest.mark.asyncio
async def test_skips_files_without_recognized_prefix(activity_environment, fixed_now):
    files = [
        _file(name="files/foreign", display_name="some-other-tool:upload", age=AGE_THRESHOLD * 2),
        _file(name="files/no-display", display_name=None, age=AGE_THRESHOLD * 2),
    ]
    raw, tmp = _StubRawClient(files), _StubTemporal({})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_unrecognized_prefix == 2
    assert result.deleted == 0


@pytest.mark.asyncio
async def test_files_with_valid_prefix_but_no_name_are_counted_separately(activity_environment, fixed_now):
    # Owned by us per display_name, but unusable — surface as a distinct bucket
    # so a Gemini API anomaly can be diagnosed instead of looking like an unrelated upload.
    f = types.File(name=None, display_name=_dn(1, "s1"), create_time=_NOW - AGE_THRESHOLD * 2)
    raw, tmp = _StubRawClient([f]), _StubTemporal({})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_no_name == 1
    assert result.skipped_unrecognized_prefix == 0
    assert result.deleted == 0


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
async def test_deletes_files_for_terminal_workflows(activity_environment, fixed_now, status):
    f = _file(name="files/old", display_name=_dn(1, "s1"), age=AGE_THRESHOLD * 2)
    raw, tmp = _StubRawClient([f]), _StubTemporal({_wid(1, "s1"): _Outcome(status=status)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.deleted == 1
    assert raw.files.deleted == ["files/old"]


@pytest.mark.parametrize(
    "status",
    [WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CONTINUED_AS_NEW],
)
@pytest.mark.asyncio
async def test_skips_files_for_active_workflows(activity_environment, fixed_now, status):
    f = _file(name="files/in-use", display_name=_dn(1, "s1"), age=AGE_THRESHOLD * 2)
    raw, tmp = _StubRawClient([f]), _StubTemporal({_wid(1, "s1"): _Outcome(status=status)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_running == 1
    assert result.deleted == 0
    assert raw.files.deleted == []


@pytest.mark.asyncio
async def test_files_from_other_deployments_are_skipped(activity_environment, fixed_now):
    # Sibling deployment's file: prefix matches our `session-summary:single:` workflow
    # convention but with a different deployment tag → must not be touched.
    other = _file(
        name="files/eu",
        display_name=f"OTHER:{_wid(1, 's1')}",
        age=AGE_THRESHOLD * 2,
    )
    raw, tmp = _StubRawClient([other]), _StubTemporal({})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_unrecognized_prefix == 1
    assert result.deleted == 0
    assert raw.files.deleted == []


@pytest.mark.asyncio
async def test_status_none_is_treated_as_running(activity_environment, fixed_now):
    # `WorkflowExecutionDescription.status` can come back unset; we mustn't delete on that.
    f = _file(name="files/maybe-running", display_name=_dn(1, "s1"), age=AGE_THRESHOLD * 2)
    raw, tmp = _StubRawClient([f]), _StubTemporal({_wid(1, "s1"): _Outcome(status=None)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_running == 1
    assert result.deleted == 0
    assert raw.files.deleted == []


@pytest.mark.asyncio
async def test_deletes_when_workflow_not_found(activity_environment, fixed_now):
    f = _file(name="files/orphan", display_name=_dn(1, "s1"), age=AGE_THRESHOLD * 2)
    raw, tmp = _StubRawClient([f]), _StubTemporal({_wid(1, "s1"): _Outcome(raise_not_found=True)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.deleted == 1
    assert raw.files.deleted == ["files/orphan"]


@pytest.mark.asyncio
async def test_skips_on_temporal_rpc_error(activity_environment, fixed_now):
    f = _file(name="files/unknown", display_name=_dn(1, "s1"), age=AGE_THRESHOLD * 2)
    raw, tmp = _StubRawClient([f]), _StubTemporal({_wid(1, "s1"): _Outcome(raise_rpc_error=True)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.skipped_temporal_error == 1
    assert result.deleted == 0
    assert raw.files.deleted == []


@pytest.mark.asyncio
async def test_delete_failure_counted_does_not_raise(activity_environment, fixed_now):
    files = [
        _file(name="files/ok", display_name=_dn(1, "s1"), age=AGE_THRESHOLD * 2),
        _file(name="files/bad", display_name=_dn(1, "s2"), age=AGE_THRESHOLD * 2),
    ]
    raw = _StubRawClient(files)
    raw.files.delete_raises_for = {"files/bad"}
    tmp = _StubTemporal(
        {
            _wid(1, "s1"): _Outcome(status=WorkflowExecutionStatus.COMPLETED),
            _wid(1, "s2"): _Outcome(status=WorkflowExecutionStatus.COMPLETED),
        }
    )
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.deleted == 1
    assert result.delete_failed == 1
    assert raw.files.deleted == ["files/ok"]


@pytest.mark.asyncio
async def test_hits_max_files_cap_on_candidate_count(activity_environment, fixed_now):
    files = [
        _file(name=f"files/n{i}", display_name=_dn(1, f"s{i}"), age=AGE_THRESHOLD * 2)
        for i in range(MAX_FILES_PER_SWEEP + 1)
    ]
    raw = _StubRawClient(files)
    tmp = _StubTemporal({_wid(1, f"s{i}"): _Outcome(raise_not_found=True) for i in range(MAX_FILES_PER_SWEEP + 1)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.hit_max_files_cap is True
    assert result.deleted == MAX_FILES_PER_SWEEP


@pytest.mark.asyncio
async def test_unrelated_files_do_not_consume_cap(activity_environment, fixed_now):
    # Cap counts candidates only — a backlog of foreign / young files in front of one
    # eligible orphan must not prevent the orphan from being collected and deleted.
    young_or_foreign = [
        _file(name=f"files/y{i}", display_name=_dn(1, f"y{i}"), age=dt.timedelta(seconds=1))
        for i in range(MAX_FILES_PER_SWEEP)
    ]
    orphan = _file(name="files/orphan", display_name=_dn(1, "real"), age=AGE_THRESHOLD * 2)
    raw = _StubRawClient([*young_or_foreign, orphan])
    tmp = _StubTemporal({_wid(1, "real"): _Outcome(raise_not_found=True)})
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.hit_max_files_cap is False
    assert result.deleted == 1
    assert raw.files.deleted == ["files/orphan"]


@pytest.mark.asyncio
async def test_mixed_cycle_aggregates_correctly(activity_environment, fixed_now):
    files = [
        _file(name="files/young", display_name=_dn(1, "s1"), age=dt.timedelta(minutes=10)),
        _file(name="files/foreign", display_name="other-tool:upload", age=AGE_THRESHOLD * 2),
        _file(name="files/done", display_name=_dn(1, "s2"), age=AGE_THRESHOLD * 2),
        _file(name="files/running", display_name=_dn(1, "s3"), age=AGE_THRESHOLD * 2),
        _file(name="files/orphan", display_name=_dn(1, "s4"), age=AGE_THRESHOLD * 2),
        _file(name="files/error", display_name=_dn(1, "s5"), age=AGE_THRESHOLD * 2),
    ]
    raw = _StubRawClient(files)
    tmp = _StubTemporal(
        {
            _wid(1, "s2"): _Outcome(status=WorkflowExecutionStatus.COMPLETED),
            _wid(1, "s3"): _Outcome(status=WorkflowExecutionStatus.RUNNING),
            _wid(1, "s4"): _Outcome(raise_not_found=True),
            _wid(1, "s5"): _Outcome(raise_rpc_error=True),
        }
    )
    p1, p2 = _patch_clients(raw, tmp)
    with p1, p2:
        result = await activity_environment.run(sweep_gemini_files_activity, CleanupSweepInputs())
    assert result.listed == 6
    assert result.skipped_too_young == 1
    assert result.skipped_unrecognized_prefix == 1
    assert result.skipped_running == 1
    assert result.skipped_temporal_error == 1
    assert result.deleted == 2
    assert sorted(raw.files.deleted) == ["files/done", "files/orphan"]
