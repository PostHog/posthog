import uuid

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ActivityError, ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.warehouse_sources_queue_partition_management.types import PartitionManagementInput
from posthog.temporal.warehouse_sources_queue_partition_management.workflows import (
    WarehouseSourcesQueuePartitionManagementWorkflow,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("errors", [[], ["Failed to create sourcebatch_20261114: canceling statement"]])
async def test_workflow_fails_without_retry_when_the_activity_reports_errors(errors: list[str]) -> None:
    calls: list[int] = []

    @activity.defn(name="manage_warehouse_sources_queue_partitions")
    async def fake_activity() -> dict:
        calls.append(1)
        return {
            "created": [],
            "already_existed": [],
            "dropped": [],
            "errors": errors,
            "alerts": [],
            "success": not errors,
        }

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[WarehouseSourcesQueuePartitionManagementWorkflow],
            activities=[fake_activity],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            run = env.client.execute_workflow(
                WarehouseSourcesQueuePartitionManagementWorkflow.run,
                PartitionManagementInput(),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )
            if not errors:
                assert (await run)["success"] is True
            else:
                with pytest.raises(WorkflowFailureError) as exc_info:
                    await run
                cause = exc_info.value.cause
                assert isinstance(cause, ApplicationError) and not isinstance(cause, ActivityError)
                assert cause.non_retryable is True
                assert list(cause.details) == [errors]

    assert len(calls) == 1
