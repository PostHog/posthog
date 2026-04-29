import dataclasses
from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

import temporalio.activity
import temporalio.workflow
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.slo.types import SloArea, SloConfig, SloOperation, SloOutcome
from posthog.temporal.common.slo_interceptor import SloInterceptor


@dataclasses.dataclass
class TrackedWorkflowInput:
    value: str = ""
    slo: SloConfig | None = None


@dataclasses.dataclass
class UntrackedWorkflowInput:
    value: str = ""


@temporalio.workflow.defn(name="test-slo-tracked")
class TrackedWorkflow:
    @temporalio.workflow.run
    async def run(self, inputs: TrackedWorkflowInput) -> str:
        if inputs.slo:
            inputs.slo.completion_properties["extra_key"] = "extra_value"
        return "ok"


@temporalio.workflow.defn(name="test-slo-tracked-failure")
class TrackedFailureWorkflow:
    @temporalio.workflow.run
    async def run(self, inputs: TrackedWorkflowInput) -> str:
        raise ApplicationError("boom", non_retryable=True)


@temporalio.workflow.defn(name="test-slo-tracked-business-failure")
class TrackedBusinessFailureWorkflow:
    @temporalio.workflow.run
    async def run(self, inputs: TrackedWorkflowInput) -> str:
        if inputs.slo:
            inputs.slo.outcome = SloOutcome.FAILURE
            inputs.slo.completion_properties["reason"] = "business logic"
        return "ok"


@temporalio.activity.defn
async def failing_activity() -> None:
    raise ApplicationError("activity boom", type="ActivityBoom", non_retryable=True)


@temporalio.workflow.defn(name="test-slo-activity-failure")
class TrackedActivityFailureWorkflow:
    @temporalio.workflow.run
    async def run(self, inputs: TrackedWorkflowInput) -> str:
        await temporalio.workflow.execute_activity(
            failing_activity,
            schedule_to_close_timeout=timedelta(seconds=10),
        )
        return "ok"


@temporalio.workflow.defn(name="test-slo-override-error-trace")
class TrackedOverrideErrorTraceWorkflow:
    @temporalio.workflow.run
    async def run(self, inputs: TrackedWorkflowInput) -> str:
        try:
            raise ApplicationError("boom", non_retryable=True)
        except ApplicationError:
            # Pre-populate error_trace — the interceptor's setdefault must not clobber it.
            if inputs.slo:
                inputs.slo.completion_properties["error_trace"] = "pre-populated by workflow"
            raise


@temporalio.workflow.defn(name="test-slo-untracked")
class UntrackedWorkflow:
    @temporalio.workflow.run
    async def run(self, inputs: UntrackedWorkflowInput) -> str:
        return "ok"


def _make_slo_config(start_properties: dict | None = None) -> SloConfig:
    return SloConfig(
        operation=SloOperation.EXPORT,
        area=SloArea.ANALYTIC_PLATFORM,
        team_id=1,
        resource_id="42",
        distinct_id="user-123",
        start_properties=start_properties or {},
    )


def _get_slo_calls(mock_analytics: MagicMock, event: str) -> list:
    return [c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == event]


pytestmark = [pytest.mark.asyncio]


@pytest.mark.parametrize(
    "workflow_cls,slo_config,raises,expected_outcome,extra_completed_checks,expect_error_trace",
    [
        (
            TrackedWorkflow,
            _make_slo_config(start_properties={"source": "web"}),
            False,
            SloOutcome.SUCCESS,
            {"extra_key": "extra_value"},
            False,
        ),
        (
            TrackedFailureWorkflow,
            _make_slo_config(),
            True,
            SloOutcome.FAILURE,
            {"error_type": "ApplicationError", "error_message": "boom"},
            True,
        ),
        (
            TrackedActivityFailureWorkflow,
            _make_slo_config(),
            True,
            SloOutcome.FAILURE,
            {"error_type": "ActivityBoom", "error_message": "ActivityBoom: activity boom"},
            True,
        ),
        (
            TrackedBusinessFailureWorkflow,
            _make_slo_config(),
            False,
            SloOutcome.FAILURE,
            {"reason": "business logic"},
            False,
        ),
    ],
    ids=["success_with_completion_props", "exception_failure", "activity_failure_unwrap", "business_logic_failure"],
)
@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_emits_slo_events(
    mock_analytics: MagicMock,
    workflow_cls,
    slo_config: SloConfig,
    raises: bool,
    expected_outcome: SloOutcome,
    extra_completed_checks: dict,
    expect_error_trace: bool,
):
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[workflow_cls],
            activities=[failing_activity],
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            execute = env.client.execute_workflow(
                workflow_cls.run,
                TrackedWorkflowInput(value="test", slo=slo_config),
                id=f"test-{workflow_cls.__name__}",
                task_queue="test-slo",
            )
            if raises:
                with pytest.raises(Exception):
                    await execute
            else:
                await execute

    started_calls = _get_slo_calls(mock_analytics, "slo_operation_started")
    assert len(started_calls) == 1
    started_props = started_calls[0].kwargs["properties"]
    assert started_props["operation"] == "export"
    assert started_props["resource_id"] == "42"
    assert started_props["correlation_id"] is not None
    assert started_props["workflow_type"] == workflow_cls.__temporal_workflow_definition.name

    completed_calls = _get_slo_calls(mock_analytics, "slo_operation_completed")
    assert len(completed_calls) == 1
    completed_props = completed_calls[0].kwargs["properties"]
    assert completed_props["outcome"] == expected_outcome
    assert completed_props["duration_ms"] is not None
    assert completed_props["correlation_id"] == started_props["correlation_id"]
    for key, value in extra_completed_checks.items():
        assert completed_props[key] == value
    if expect_error_trace:
        # The interceptor populates error_trace from either the activity-side
        # ApplicationError.details[0] or a fallback workflow-side traceback.
        assert completed_props.get("error_trace") is not None
    else:
        # Successful workflows and in-workflow business-failure paths never raise,
        # so the interceptor has nothing to unwrap — error_trace must not be set.
        assert "error_trace" not in completed_props


@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_respects_workflow_error_trace_override(mock_analytics: MagicMock):
    # Workflows can override error_trace by pre-populating completion_properties
    # before re-raising — the interceptor uses setdefault, so workflow intent wins.
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[TrackedOverrideErrorTraceWorkflow],
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(Exception):
                await env.client.execute_workflow(
                    TrackedOverrideErrorTraceWorkflow.run,
                    TrackedWorkflowInput(value="test", slo=_make_slo_config()),
                    id="test-error-trace-override",
                    task_queue="test-slo",
                )

    completed_calls = _get_slo_calls(mock_analytics, "slo_operation_completed")
    assert len(completed_calls) == 1
    props = completed_calls[0].kwargs["properties"]
    assert props["error_trace"] == "pre-populated by workflow"
    # error_type / error_message are still filled in by the interceptor
    assert props["error_type"] == "ApplicationError"
    assert props["error_message"] == "boom"


@pytest.mark.parametrize(
    "workflow_cls,input_cls,slo",
    [
        (UntrackedWorkflow, UntrackedWorkflowInput, None),
        (TrackedWorkflow, TrackedWorkflowInput, None),
    ],
    ids=["untracked_input_type", "tracked_input_with_none_slo"],
)
@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_skips_untracked_workflows(
    mock_analytics: MagicMock,
    workflow_cls,
    input_cls,
    slo,
):
    inputs = (
        input_cls(value="test")
        if slo is None and input_cls == UntrackedWorkflowInput
        else input_cls(value="test", slo=slo)
    )
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[workflow_cls],
            activities=[failing_activity],
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                workflow_cls.run,
                inputs,
                id=f"test-skip-{workflow_cls.__name__}",
                task_queue="test-slo",
            )

    assert result == "ok"
    assert mock_analytics.capture.call_count == 0
