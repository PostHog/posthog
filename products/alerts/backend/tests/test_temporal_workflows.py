import uuid
import asyncio
import logging
import datetime as dt
from collections.abc import AsyncIterator
from typing import Literal

import pytest

from django.conf import settings

import pytest_asyncio
from temporalio import activity, workflow
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.exceptions import ApplicationError, TerminatedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.facade.temporal import (
    DELIVERY_ACTIVITIES,
    DELIVERY_WORKFLOWS,
    EVALUATION_ACTIVITIES,
    EVALUATION_WORKFLOWS,
)
from products.alerts.backend.temporal.workflows import AlertsProductCheckDueWorkflow, AlertsProductInputs


@workflow.defn(name="test-alerts-product-close-after-child-start")
class CloseAfterChildStartWorkflow:
    @workflow.run
    async def run(self, close_mode: str) -> None:
        await AlertsProductCheckDueWorkflow().run(AlertsProductInputs())
        await workflow.execute_activity("test_confirm_child_start", start_to_close_timeout=dt.timedelta(seconds=5))
        if close_mode == "failed":
            raise ApplicationError("Test parent failure", non_retryable=True)
        await workflow.wait_condition(lambda: False)


@pytest_asyncio.fixture(scope="module")
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


@pytest.mark.asyncio
async def test_each_tick_starts_independent_delivery(
    environment: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    client = environment.client
    workflow_id = str(uuid.uuid4())
    child_ids: set[str] = set()

    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
        workflows=EVALUATION_WORKFLOWS,
        activities=EVALUATION_ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        for _ in range(2):
            parent = await client.start_workflow(
                "alerts-product-check-due",
                AlertsProductInputs(),
                id=workflow_id,
                task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
                execution_timeout=dt.timedelta(seconds=10),
            )
            assert await parent.result() is None
            history = await parent.fetch_history()
            children = [
                event.child_workflow_execution_started_event_attributes
                for event in history.events
                if event.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED
            ]
            assert len(children) == 1
            child_id = children[0].workflow_execution.workflow_id
            assert parent.first_execution_run_id is not None
            assert parent.first_execution_run_id in child_id
            assert children[0].workflow_type.name == "alerts-product-deliver"
            child_ids.add(child_id)
            child = await client.get_workflow_handle(child_id).describe()
            assert child.task_queue == settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE
            assert child.status == WorkflowExecutionStatus.RUNNING

    assert len(child_ids) == 2
    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
        workflows=DELIVERY_WORKFLOWS,
        activities=DELIVERY_ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        for child_id in child_ids:
            assert await client.get_workflow_handle(child_id).result() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("close_mode", ["failed", "terminated"])
async def test_delivery_survives_parent_closure(
    environment: WorkflowEnvironment, caplog: pytest.LogCaptureFixture, close_mode: Literal["failed", "terminated"]
) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    client = environment.client
    child_started = asyncio.Event()

    @activity.defn(name="test_confirm_child_start")
    async def confirm_child_start() -> None:
        child_started.set()

    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
        workflows=[CloseAfterChildStartWorkflow],
        activities=[*EVALUATION_ACTIVITIES, confirm_child_start],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        parent = await client.start_workflow(
            CloseAfterChildStartWorkflow.run,
            close_mode,
            id=str(uuid.uuid4()),
            task_queue=settings.ALERTS_PRODUCT_EVALUATION_TASK_QUEUE,
            execution_timeout=dt.timedelta(seconds=10),
        )
        await asyncio.wait_for(child_started.wait(), timeout=10)
        child_id = f"alerts-product-deliver-{parent.first_execution_run_id}"

        if close_mode == "terminated":
            await parent.terminate()
        with pytest.raises(WorkflowFailureError) as failure:
            await parent.result()
        assert isinstance(failure.value.cause, ApplicationError if close_mode == "failed" else TerminatedError)

    child = client.get_workflow_handle(child_id)
    assert (await child.describe()).status == WorkflowExecutionStatus.RUNNING
    async with Worker(
        client,
        task_queue=settings.ALERTS_PRODUCT_DELIVERY_TASK_QUEUE,
        workflows=DELIVERY_WORKFLOWS,
        activities=DELIVERY_ACTIVITIES,
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        assert await child.result() is None
