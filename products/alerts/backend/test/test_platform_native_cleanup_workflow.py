import uuid
import datetime as dt
from collections.abc import AsyncIterator

import pytest

import pytest_asyncio
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.platform_native_cleanup import NativeCleanupInputs
from products.alerts.backend.temporal.platform_native_cleanup import (
    DELETES_AT_ONCE,
    DeleteNativeAlertInputs,
    InsightAlertNativeCleanupWorkflow,
)

QUEUE = "test-insight-native-cleanup"


@pytest_asyncio.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


async def test_a_delete_that_fails_is_retried_until_every_alert_is_gone(environment: WorkflowEnvironment) -> None:
    attempts: dict[str, int] = {}

    @activity.defn(name="list_native_insight_alerts_activity")
    async def list_alerts(inputs: NativeCleanupInputs) -> list[str]:
        return ["first", "second"]

    @activity.defn(name="delete_native_insight_alert_activity")
    async def delete(inputs: DeleteNativeAlertInputs) -> None:
        attempts[inputs.configuration_id] = activity.info().attempt
        if inputs.configuration_id == "first" and activity.info().attempt == 1:
            raise ApplicationError("database restarted")

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[InsightAlertNativeCleanupWorkflow],
        activities=[list_alerts, delete],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        deleted = await environment.client.execute_workflow(
            InsightAlertNativeCleanupWorkflow.run,
            NativeCleanupInputs(team_id=1, insight_ids=(7,)),
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
            execution_timeout=dt.timedelta(hours=1),
        )

    assert (deleted, attempts) == (2, {"first": 2, "second": 1})


async def test_a_delete_that_keeps_failing_does_not_stop_the_batches_after_it(environment: WorkflowEnvironment) -> None:
    alert_ids = [f"alert-{index}" for index in range(DELETES_AT_ONCE + 1)]
    deleted: list[str] = []

    @activity.defn(name="list_native_insight_alerts_activity")
    async def list_alerts(inputs: NativeCleanupInputs) -> list[str]:
        return alert_ids

    @activity.defn(name="delete_native_insight_alert_activity")
    async def delete(inputs: DeleteNativeAlertInputs) -> None:
        if inputs.configuration_id == alert_ids[0]:
            raise ApplicationError("the platform refused the delete", non_retryable=True)
        deleted.append(inputs.configuration_id)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[InsightAlertNativeCleanupWorkflow],
        activities=[list_alerts, delete],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        with pytest.raises(WorkflowFailureError):
            await environment.client.execute_workflow(
                InsightAlertNativeCleanupWorkflow.run,
                NativeCleanupInputs(team_id=1, insight_ids=(7,)),
                id=f"test-{uuid.uuid4()}",
                task_queue=QUEUE,
                execution_timeout=dt.timedelta(hours=1),
            )

    assert sorted(deleted) == sorted(alert_ids[1:])
