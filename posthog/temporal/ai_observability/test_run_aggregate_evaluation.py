import uuid
from datetime import timedelta
from typing import Any

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.evaluation_workflow_activities import RunEvaluationInputs
from posthog.temporal.ai_observability.run_aggregate_evaluation import (
    RunAggregateEvaluationInputs,
    RunAggregateEvaluationWorkflow,
    resolve_settle_plan,
)
from posthog.temporal.ai_observability.run_trace_evaluation import (
    EmitTraceEvaluationEventInputs,
    ExecuteTraceEvaluationInputs,
)


class TestResolveSettlePlan:
    @pytest.mark.parametrize(
        "settle,expected",
        [
            (None, ("fixed_window", 1800, 1800)),
            ({}, ("fixed_window", 1800, 1800)),
            ({"strategy": "fixed_window", "window_seconds": 60}, ("fixed_window", 60, 60)),
            # Legacy sub-floor values are bumped to the floor (the old workflow only re-clamped the max).
            ({"window_seconds": 0}, ("fixed_window", 10, 10)),
            ({"window_seconds": 99999}, ("fixed_window", 7200, 7200)),
            ({"strategy": "inactivity"}, ("inactivity", 300, 7200)),
            (
                {"strategy": "inactivity", "quiet_period_seconds": 120, "max_age_seconds": 600},
                ("inactivity", 120, 600),
            ),
            # Sub-floor and above-ceiling quiet_period_seconds are clamped the same way as window_seconds.
            ({"strategy": "inactivity", "quiet_period_seconds": 5}, ("inactivity", 10, 7200)),
            ({"strategy": "inactivity", "quiet_period_seconds": 5000}, ("inactivity", 1800, 7200)),
            # max_age below quiet period is coerced up so the loop's min() can't fire before one quiet period.
            (
                {"strategy": "inactivity", "quiet_period_seconds": 600, "max_age_seconds": 60},
                ("inactivity", 600, 600),
            ),
            ({"strategy": "bogus", "window_seconds": 60}, ("fixed_window", 60, 60)),
        ],
    )
    def test_resolves_and_clamps(self, settle, expected):
        assert resolve_settle_plan(settle) == expected


def _mock_activities(calls: list[str]) -> list[Any]:
    @activity.defn(name="fetch_evaluation_activity")
    async def mock_fetch_evaluation(inputs: RunEvaluationInputs) -> dict[str, Any]:
        calls.append("fetch")
        return {
            "id": inputs.evaluation_id,
            "name": "Hog eval",
            "evaluation_type": "hog",
            "evaluation_config": {},
            "output_type": "boolean",
            "output_config": {},
            "team_id": 1,
            "enabled": True,
            "deleted": False,
        }

    @activity.defn(name="execute_trace_hog_eval_activity")
    async def mock_execute_trace_hog(inputs: ExecuteTraceEvaluationInputs) -> EvaluationActivityResult:
        calls.append("execute")
        return {"result_type": "boolean", "verdict": True, "reasoning": "ok", "allows_na": False}

    @activity.defn(name="emit_trace_evaluation_event_activity")
    async def mock_emit(inputs: EmitTraceEvaluationEventInputs) -> None:
        calls.append("emit")

    @activity.defn(name="emit_internal_telemetry_activity")
    async def mock_telemetry(inputs: Any) -> None:
        calls.append("telemetry")

    return [mock_fetch_evaluation, mock_execute_trace_hog, mock_emit, mock_telemetry]


def _workflow_inputs(settle: dict[str, Any]) -> RunAggregateEvaluationInputs:
    return RunAggregateEvaluationInputs(
        evaluation_id=str(uuid.uuid4()),
        team_id=1,
        trace_id="trace-123",
        distinct_id="user-1",
        session_id=None,
        settle=settle,
    )


class TestRunAggregateEvaluationWorkflow:
    @pytest.mark.asyncio
    async def test_fixed_window_sleeps_then_evaluates(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=_mock_activities(calls),
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                start = await env.get_current_time()
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "fixed_window", "window_seconds": 600}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    start_signal="activity-seen",
                    start_signal_args=[{"event_uuid": "first-generation"}],
                )
                await env.sleep(200)
                await handle.signal("activity-seen", {"event_uuid": "mid-window"})
                result = await handle.result()
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        assert result["verdict"] is True
        # fixed_window ignores both the start-time and mid-window signals: window stays [600, 900).
        assert elapsed >= timedelta(seconds=600)
        assert elapsed < timedelta(seconds=900)

    @pytest.mark.asyncio
    async def test_inactivity_settles_after_one_quiet_period_when_silent(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=_mock_activities(calls),
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                start = await env.get_current_time()
                await env.client.execute_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 7200}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    start_signal="activity-seen",
                    start_signal_args=[{"event_uuid": "first-generation"}],
                )
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        assert elapsed >= timedelta(seconds=300)
        assert elapsed < timedelta(seconds=600)

    @pytest.mark.asyncio
    async def test_inactivity_signal_rearms_quiet_period(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=_mock_activities(calls),
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                start = await env.get_current_time()
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 7200}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    start_signal="activity-seen",
                    start_signal_args=[{"event_uuid": "first-generation"}],
                )
                await env.sleep(120)
                await handle.signal("activity-seen", {"event_uuid": "later-generation"})
                await handle.result()
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        # Signal at ~120s re-arms the 300s quiet timer: settles at ~420s, not 300s.
        assert elapsed >= timedelta(seconds=420)
        assert elapsed < timedelta(seconds=720)

    @pytest.mark.asyncio
    async def test_inactivity_max_age_caps_a_chatty_trace(self):
        calls: list[str] = []
        task_queue = str(uuid.uuid4())
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=task_queue,
                workflows=[RunAggregateEvaluationWorkflow],
                activities=_mock_activities(calls),
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                start = await env.get_current_time()
                handle = await env.client.start_workflow(
                    RunAggregateEvaluationWorkflow.run,
                    _workflow_inputs({"strategy": "inactivity", "quiet_period_seconds": 300, "max_age_seconds": 400}),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    start_signal="activity-seen",
                    start_signal_args=[{"event_uuid": "first-generation"}],
                )
                await env.sleep(250)
                await handle.signal("activity-seen", {"event_uuid": "still-going"})
                await handle.result()
                elapsed = (await env.get_current_time()) - start
        assert calls == ["fetch", "execute", "emit", "telemetry"]
        # Signal at ~250s would re-arm to ~550s, but max_age 400s wins.
        assert elapsed >= timedelta(seconds=400)
        assert elapsed < timedelta(seconds=550)
