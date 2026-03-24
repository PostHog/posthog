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


pytestmark = [pytest.mark.asyncio]


@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_emits_started_and_completed_on_success(mock_analytics: MagicMock):
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[TrackedWorkflow],
            activities=[],
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                TrackedWorkflow.run,
                TrackedWorkflowInput(
                    value="test",
                    slo=_make_slo_config(start_properties={"source": "web"}),
                ),
                id="test-success",
                task_queue="test-slo",
            )

    assert result == "ok"

    started_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_started"
    ]
    assert len(started_calls) == 1
    started_props = started_calls[0].kwargs["properties"]
    assert started_props["operation"] == "export"
    assert started_props["team_id"] == 1
    assert started_props["resource_id"] == "42"
    assert started_props["source"] == "web"

    completed_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    completed_props = completed_calls[0].kwargs["properties"]
    assert completed_props["outcome"] == SloOutcome.SUCCESS
    assert completed_props["extra_key"] == "extra_value"
    assert completed_props["duration_ms"] is not None


@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_emits_failure_on_exception(mock_analytics: MagicMock):
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[TrackedFailureWorkflow],
            activities=[],
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(Exception):
                await env.client.execute_workflow(
                    TrackedFailureWorkflow.run,
                    TrackedWorkflowInput(slo=_make_slo_config()),
                    id="test-failure",
                    task_queue="test-slo",
                )

    completed_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    assert completed_calls[0].kwargs["properties"]["outcome"] == SloOutcome.FAILURE


@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_respects_workflow_outcome_override(mock_analytics: MagicMock):
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[TrackedBusinessFailureWorkflow],
            activities=[],
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                TrackedBusinessFailureWorkflow.run,
                TrackedWorkflowInput(slo=_make_slo_config()),
                id="test-business-failure",
                task_queue="test-slo",
            )

    assert result == "ok"

    completed_calls = [
        c for c in mock_analytics.capture.call_args_list if c.kwargs.get("event") == "slo_operation_completed"
    ]
    assert len(completed_calls) == 1
    props = completed_calls[0].kwargs["properties"]
    assert props["outcome"] == SloOutcome.FAILURE
    assert props["reason"] == "business logic"


@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_passes_through_untracked_workflows(mock_analytics: MagicMock):
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[UntrackedWorkflow],
            activities=[],
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                UntrackedWorkflow.run,
                UntrackedWorkflowInput(value="test"),
                id="test-untracked",
                task_queue="test-slo",
            )

    assert result == "ok"
    assert mock_analytics.capture.call_count == 0


@patch("posthog.slo.events.posthoganalytics")
async def test_interceptor_passes_through_none_slo(mock_analytics: MagicMock):
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(
            env.client,
            task_queue="test-slo",
            workflows=[TrackedWorkflow],
            activities=[],
            interceptors=[SloInterceptor()],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                TrackedWorkflow.run,
                TrackedWorkflowInput(value="test", slo=None),
                id="test-none-slo",
                task_queue="test-slo",
            )

    assert result == "ok"
    assert mock_analytics.capture.call_count == 0
