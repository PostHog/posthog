import uuid

import pytest

import temporalio.worker
import temporalio.workflow
from temporalio import activity
from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest
from temporalio.client import WorkflowHistory
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes
from temporalio.exceptions import (
    ActivityError,
    ApplicationError,
    TimeoutError as TemporalTimeoutError,
    TimeoutType,
)
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import BumpStuckCounterInput
from posthog.temporal.session_replay.rasterize_recording.types import (
    BuildRasterizationResult,
    FinalizeRasterizationInput,
    RasterizationActivityOutput,
    RasterizeRecordingInputs,
    RecordRasterizationFailureInput,
)
from posthog.temporal.session_replay.rasterize_recording.workflow import RasterizeRecordingWorkflow, _resolve_error_code


def _record_failure_into(calls: list[RecordRasterizationFailureInput]):
    @activity.defn(name="record_rasterization_failure")
    async def record_mocked(inputs: RecordRasterizationFailureInput) -> None:
        calls.append(inputs)

    return record_mocked


async def _register_search_attributes(env: WorkflowEnvironment) -> None:
    # Time-skipping test envs come without our custom attrs registered.
    await env.client.operator_service.add_search_attributes(
        AddSearchAttributesRequest(
            namespace="default",
            search_attributes={
                "PostHogTeamId": IndexedValueType.INDEXED_VALUE_TYPE_INT,
                "PostHogSessionRecordingId": IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD,
            },
        )
    )


def _search_attributes(team_id: int = 7, session_id: str = "sess-123") -> TypedSearchAttributes:
    return TypedSearchAttributes(
        search_attributes=[
            SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=team_id),
            SearchAttributePair(key=POSTHOG_SESSION_RECORDING_ID_KEY, value=session_id),
        ]
    )


async def _run_terminally_failing_workflow(
    session_id: str, record_calls: list[RecordRasterizationFailureInput], *, fail_at: str = "prep"
) -> list[BumpStuckCounterInput]:
    """One workflow run whose first (and only) attempt fails at `fail_at` (prep or render); returns the bump inputs."""
    from django.conf import settings

    from posthog.temporal.session_replay.rasterize_recording.types import RasterizationActivityInput

    bump_calls: list[BumpStuckCounterInput] = []

    @activity.defn(name="build_rasterization_input")
    async def build_mocked(_exported_asset_id: int) -> BuildRasterizationResult:
        if fail_at == "prep":
            raise RuntimeError("synthetic prep failure")
        return BuildRasterizationResult(
            activity_input=RasterizationActivityInput(
                session_id=session_id, team_id=7, s3_bucket="bucket", s3_key_prefix="prefix"
            ),
            render_fingerprint="abc",
        )

    @activity.defn(name="rasterize-recording")
    async def render_failing(_inputs: dict) -> dict:
        raise ApplicationError("synthetic render failure", non_retryable=True)

    @activity.defn(name="finalize_rasterization")
    async def finalize_unused(_inputs: FinalizeRasterizationInput) -> None:
        pass  # not reached on failure

    @activity.defn(name="bump_stuck_counter_activity")
    async def bump_mocked(inputs: BumpStuckCounterInput) -> None:
        bump_calls.append(inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        await _register_search_attributes(env)
        async with (
            Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RasterizeRecordingWorkflow],
                activities=[build_mocked, finalize_unused, bump_mocked, _record_failure_into(record_calls)],
                workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            ),
            Worker(
                env.client,
                task_queue=settings.RASTERIZATION_TASK_QUEUE,
                activities=[render_failing],
            ),
        ):
            with pytest.raises(Exception):
                await env.client.execute_workflow(
                    RasterizeRecordingWorkflow.run,
                    RasterizeRecordingInputs(exported_asset_id=42),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    # maximum_attempts=1 so the FIRST failure is the terminal one.
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    search_attributes=_search_attributes(team_id=7, session_id=session_id),
                )
    return bump_calls


@pytest.mark.asyncio
async def test_terminal_failure_bumps_stuck_counter():
    record_calls: list[RecordRasterizationFailureInput] = []

    bump_calls = await _run_terminally_failing_workflow("sess-123", record_calls)

    assert bump_calls == [BumpStuckCounterInput(team_id=7, session_id="sess-123")]
    # The code has to come off the wrapped cause, not the ActivityError Temporal raises here.
    # Reading the wrapper would classify every video failure identically.
    assert [(call.exported_asset_id, call.error_code) for call in record_calls] == [(42, "RuntimeError")]


@pytest.mark.asyncio
async def test_killed_worker_render_failure_quarantines_immediately(monkeypatch):
    # A timeout-class final failure in the render phase must bump with killed_worker=True, or a
    # worker-killing recording waits for a second whole retry envelope before the quarantine
    # engages. The classifier is patched because the test server cannot mint a real heartbeat
    # timeout without a live worker hanging for the full 30s timeout; the classifier itself is
    # covered by test_resolve_error_code_maps_temporal_timeouts.
    monkeypatch.setattr(
        "posthog.temporal.session_replay.rasterize_recording.workflow._resolve_error_code",
        lambda _exc: "ACTIVITY_TIMEOUT",
    )

    bump_calls = await _run_terminally_failing_workflow("sess-huge", [], fail_at="render")

    assert bump_calls == [BumpStuckCounterInput(team_id=7, session_id="sess-huge", killed_worker=True)]


@pytest.mark.asyncio
async def test_timeout_outside_the_render_phase_does_not_quarantine(monkeypatch):
    # A timed-out prep activity (a Postgres incident, not the recording) must stay on the ordinary
    # two-strike path; quarantining it for 24h would silence scans for sessions the renderer never opened.
    monkeypatch.setattr(
        "posthog.temporal.session_replay.rasterize_recording.workflow._resolve_error_code",
        lambda _exc: "ACTIVITY_TIMEOUT",
    )

    bump_calls = await _run_terminally_failing_workflow("sess-db-blip", [], fail_at="prep")

    assert bump_calls == [BumpStuckCounterInput(team_id=7, session_id="sess-db-blip", killed_worker=False)]


def _scheduled_activities(history: WorkflowHistory) -> list[str]:
    return [
        event.activity_task_scheduled_event_attributes.activity_type.name
        for event in history.events
        if event.HasField("activity_task_scheduled_event_attributes")
    ]


@pytest.mark.asyncio
async def test_failure_recording_stays_behind_its_patch(monkeypatch):
    """A video export already running when this deploys must not gain a command mid-flight.

    An execution replaying a history that predates the patch has to take the old path exactly, or it
    dies with a non-determinism error rather than finishing. Asserting the pre-patch run schedules no
    failure activity is what holds the gate in place: drop the gate and this run gains one.
    """

    @activity.defn(name="build_rasterization_input")
    async def build_failing(_exported_asset_id: int) -> BuildRasterizationResult:
        raise RuntimeError("synthetic prep failure")

    @activity.defn(name="finalize_rasterization")
    async def finalize_unused(_inputs: FinalizeRasterizationInput) -> None:
        pass

    @activity.defn(name="bump_stuck_counter_activity")
    async def bump_noop(_inputs: BumpStuckCounterInput) -> None:
        pass

    async def _run_to_failure(env: WorkflowEnvironment, task_queue: str) -> WorkflowHistory:
        handle = await env.client.start_workflow(
            RasterizeRecordingWorkflow.run,
            RasterizeRecordingInputs(exported_asset_id=42),
            id=str(uuid.uuid4()),
            task_queue=task_queue,
            retry_policy=RetryPolicy(maximum_attempts=1),
            search_attributes=_search_attributes(),
        )
        with pytest.raises(Exception):
            await handle.result()
        return await handle.fetch_history()

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        await _register_search_attributes(env)
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RasterizeRecordingWorkflow],
            activities=[build_failing, finalize_unused, bump_noop, _record_failure_into([])],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            # `patched` reports False against a history recorded before the patch existed.
            monkeypatch.setattr(temporalio.workflow, "patched", lambda _patch_id: False)
            pre_patch_history = await _run_to_failure(env, task_queue)
            monkeypatch.undo()

            patched_history = await _run_to_failure(env, task_queue)

    assert "record_rasterization_failure" not in _scheduled_activities(pre_patch_history)
    assert "record_rasterization_failure" in _scheduled_activities(patched_history)

    await Replayer(
        workflows=[RasterizeRecordingWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ).replay_workflow(pre_patch_history)


@pytest.mark.asyncio
async def test_intermediate_failure_does_not_bump():
    bump_calls: list[BumpStuckCounterInput] = []
    attempts = {"count": 0}

    @activity.defn(name="build_rasterization_input")
    async def build_flaky(_exported_asset_id: int) -> BuildRasterizationResult:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("transient prep failure")
        # Second attempt succeeds via cache fast-path
        return BuildRasterizationResult(
            cached_output=RasterizationActivityOutput(
                s3_uri="s3://bucket/key",
                video_duration_s=1.0,
                playback_speed=1.0,
            ),
            render_fingerprint="abc",
        )

    @activity.defn(name="finalize_rasterization")
    async def finalize_unused(_inputs: FinalizeRasterizationInput) -> None:
        pass

    @activity.defn(name="bump_stuck_counter_activity")
    async def bump_mocked(inputs: BumpStuckCounterInput) -> None:
        bump_calls.append(inputs)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        await _register_search_attributes(env)
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RasterizeRecordingWorkflow],
            activities=[build_flaky, finalize_unused, bump_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            # Workflow-level retries: first attempt fails, second succeeds.
            await env.client.execute_workflow(
                RasterizeRecordingWorkflow.run,
                RasterizeRecordingInputs(exported_asset_id=42),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                retry_policy=RetryPolicy(maximum_attempts=2),
                search_attributes=_search_attributes(),
            )

    # No bump because the intermediate failure recovered.
    assert bump_calls == []


def _counter_value(product: str, task_queue: str) -> float:
    from prometheus_client import REGISTRY

    return (
        REGISTRY.get_sample_value(
            "posthog_rasterization_completed_total",
            {"product": product, "task_queue": task_queue},
        )
        or 0.0
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["session_replay", "replay_vision"])
async def test_success_increments_rasterization_counter(product: str):
    @activity.defn(name="build_rasterization_input")
    async def build_cached(_exported_asset_id: int) -> BuildRasterizationResult:
        return BuildRasterizationResult(
            cached_output=RasterizationActivityOutput(
                s3_uri="s3://bucket/key",
                video_duration_s=1.0,
                playback_speed=1.0,
            ),
            render_fingerprint="abc",
        )

    @activity.defn(name="finalize_rasterization")
    async def finalize_noop(_inputs: FinalizeRasterizationInput) -> None:
        pass

    @activity.defn(name="clear_stuck_counter_activity")
    async def clear_noop(_inputs: BumpStuckCounterInput) -> None:
        pass

    task_queue = str(uuid.uuid4())
    before = _counter_value(product, task_queue)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        await _register_search_attributes(env)
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RasterizeRecordingWorkflow],
            activities=[build_cached, finalize_noop, clear_noop],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                RasterizeRecordingWorkflow.run,
                RasterizeRecordingInputs(exported_asset_id=42, product=product),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                retry_policy=RetryPolicy(maximum_attempts=1),
                search_attributes=_search_attributes(),
            )

    assert _counter_value(product, task_queue) == before + 1


@pytest.mark.asyncio
async def test_failure_does_not_increment_rasterization_counter():
    @activity.defn(name="build_rasterization_input")
    async def build_failing(_exported_asset_id: int) -> BuildRasterizationResult:
        raise RuntimeError("synthetic prep failure")

    @activity.defn(name="finalize_rasterization")
    async def finalize_unused(_inputs: FinalizeRasterizationInput) -> None:
        pass

    @activity.defn(name="bump_stuck_counter_activity")
    async def bump_noop(_inputs: BumpStuckCounterInput) -> None:
        pass

    task_queue = str(uuid.uuid4())
    before = _counter_value("session_replay", task_queue)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        await _register_search_attributes(env)
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RasterizeRecordingWorkflow],
            activities=[build_failing, finalize_unused, bump_noop, _record_failure_into([])],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(Exception):
                await env.client.execute_workflow(
                    RasterizeRecordingWorkflow.run,
                    RasterizeRecordingInputs(exported_asset_id=42),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    search_attributes=_search_attributes(),
                )

    assert _counter_value("session_replay", task_queue) == before


@pytest.mark.asyncio
async def test_bump_failure_does_not_break_workflow_failure():
    @activity.defn(name="build_rasterization_input")
    async def build_failing(_exported_asset_id: int) -> BuildRasterizationResult:
        raise RuntimeError("synthetic prep failure")

    @activity.defn(name="finalize_rasterization")
    async def finalize_unused(_inputs: FinalizeRasterizationInput) -> None:
        pass

    @activity.defn(name="bump_stuck_counter_activity")
    async def bump_failing(inputs: BumpStuckCounterInput) -> None:
        raise RuntimeError("redis down")

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        await _register_search_attributes(env)
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RasterizeRecordingWorkflow],
            activities=[build_failing, finalize_unused, bump_failing, _record_failure_into([])],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(Exception):
                await env.client.execute_workflow(
                    RasterizeRecordingWorkflow.run,
                    RasterizeRecordingInputs(exported_asset_id=42),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    search_attributes=_search_attributes(),
                )


def test_resolve_error_code_maps_temporal_timeouts():
    """A worker that dies by heartbeat or start-to-close timeout raises no ApplicationError, so
    without the explicit TimeoutError check the asset would classify as an opaque ActivityError.
    The TimeoutError sits directly on the raised error or one wrapper deeper depending on where
    the deadline fired."""
    timeout = TemporalTimeoutError("activity timed out", type=TimeoutType.START_TO_CLOSE, last_heartbeat_details=[])
    wrapped = _activity_error()
    wrapped.__cause__ = timeout

    assert _resolve_error_code(timeout) == "ACTIVITY_TIMEOUT"
    assert _resolve_error_code(wrapped) == "ACTIVITY_TIMEOUT"


def test_resolve_error_code_keeps_the_renderers_own_code():
    error = _activity_error()
    error.__cause__ = ApplicationError("render failed", type="NO_SNAPSHOTS")

    assert _resolve_error_code(error) == "NO_SNAPSHOTS"


def _activity_error() -> ActivityError:
    return ActivityError(
        "activity failed",
        scheduled_event_id=1,
        started_event_id=1,
        identity="worker",
        activity_type="rasterize",
        activity_id="1",
        retry_state=None,
    )
