import dataclasses

import pytest
from unittest.mock import MagicMock, patch

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
    "workflow_cls,slo_config,raises,expected_outcome,extra_completed_checks",
    [
        (
            TrackedWorkflow,
            _make_slo_config(start_properties={"source": "web"}),
            False,
            SloOutcome.SUCCESS,
            {"extra_key": "extra_value"},
        ),
        (
            TrackedFailureWorkflow,
            _make_slo_config(),
            True,
            SloOutcome.FAILURE,
            {},
        ),
        (
            TrackedBusinessFailureWorkflow,
            _make_slo_config(),
            False,
            SloOutcome.FAILURE,
            {"reason": "business logic"},
        ),
    ],
    ids=["success_with_completion_props", "exception_failure", "business_logic_failure"],
)
@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_emits_slo_events(
    mock_analytics: MagicMock,
    workflow_cls,
    slo_config: SloConfig,
    raises: bool,
    expected_outcome: SloOutcome,
    extra_completed_checks: dict,
):
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[workflow_cls],
            activities=[],
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
    assert started_props["workflow_run_id"] is not None
    assert started_props["workflow_type"] == workflow_cls.__temporal_workflow_definition.name

    completed_calls = _get_slo_calls(mock_analytics, "slo_operation_completed")
    assert len(completed_calls) == 1
    completed_props = completed_calls[0].kwargs["properties"]
    assert completed_props["outcome"] == expected_outcome
    assert completed_props["duration_ms"] is not None
    assert completed_props["workflow_run_id"] == started_props["workflow_run_id"]
    for key, value in extra_completed_checks.items():
        assert completed_props[key] == value


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
            activities=[],
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
