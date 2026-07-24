import uuid
import datetime as dt

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.api.enums.v1 import IndexedValueType
from temporalio.api.operatorservice.v1 import AddSearchAttributesRequest
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.common.search_attributes import POSTHOG_SESSION_RECORDING_ID_KEY, POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import BumpStuckCounterInput
from posthog.temporal.session_replay.rasterize_recording.types import (
    RASTERIZE_MAX_TIMEOUT,
    RASTERIZE_MIN_TIMEOUT,
    BuildRasterizationResult,
    FinalizeRasterizationInput,
    RasterizationActivityInput,
    RasterizationActivityOutput,
    RasterizeRecordingInputs,
    rasterize_activity_timeout,
)
from posthog.temporal.session_replay.rasterize_recording.workflow import RasterizeRecordingWorkflow


def _activity_input(**overrides) -> RasterizationActivityInput:
    base = {"session_id": "s", "team_id": 1, "s3_bucket": "b", "s3_key_prefix": "p"}
    return RasterizationActivityInput(**{**base, **overrides})


@pytest.mark.parametrize(
    "start_offset_s,end_offset_s,expected",
    [
        # No end offset (e.g. replay_vision) — allow the most headroom.
        (None, None, RASTERIZE_MAX_TIMEOUT),
        # Short clip — floored at the minimum so we never regress below the old ceiling.
        (0.0, 30.0, RASTERIZE_MIN_TIMEOUT),
        # 2h recording — the case that used to time out at 30m — gets well over 30m.
        (0.0, 7200.0, dt.timedelta(minutes=70)),
        # Very long recording — capped so a single render can't tie up a worker indefinitely.
        (0.0, 100_000.0, RASTERIZE_MAX_TIMEOUT),
        # Only the played span counts, not the absolute offset.
        (100.0, 130.0, RASTERIZE_MIN_TIMEOUT),
    ],
)
def test_rasterize_activity_timeout_scales_with_clip_length(start_offset_s, end_offset_s, expected):
    timeout = rasterize_activity_timeout(_activity_input(start_offset_s=start_offset_s, end_offset_s=end_offset_s))
    assert timeout == expected
    assert RASTERIZE_MIN_TIMEOUT <= timeout <= RASTERIZE_MAX_TIMEOUT


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


@pytest.mark.asyncio
async def test_terminal_failure_bumps_stuck_counter():
    bump_calls: list[BumpStuckCounterInput] = []

    @activity.defn(name="build_rasterization_input")
    async def build_failing(_exported_asset_id: int) -> BuildRasterizationResult:
        raise RuntimeError("synthetic prep failure")

    @activity.defn(name="finalize_rasterization")
    async def finalize_unused(_inputs: FinalizeRasterizationInput) -> None:
        pass  # not reached on failure

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
            activities=[build_failing, finalize_unused, bump_mocked],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(Exception):
                await env.client.execute_workflow(
                    RasterizeRecordingWorkflow.run,
                    RasterizeRecordingInputs(exported_asset_id=42),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    # maximum_attempts=1 so the FIRST failure is the terminal one.
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    search_attributes=_search_attributes(team_id=7, session_id="sess-123"),
                )

    assert bump_calls == [BumpStuckCounterInput(team_id=7, session_id="sess-123")]


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
            activities=[build_failing, finalize_unused, bump_noop],
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
            activities=[build_failing, finalize_unused, bump_failing],
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
