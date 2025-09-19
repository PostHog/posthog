from django.conf import settings

import pytest_asyncio
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

# Import fixtures from parent temporal tests conftest.py
from posthog.temporal.hogql_query_snapshots.run_workflow import (
    RunWorkflow,
    create_snapshot_job_activity,
    finish_snapshot_job_activity,
    run_snapshot_activity,
)


@pytest_asyncio.fixture
async def snapshots_worker(temporal_client):
    """Temporal worker configured specifically for snapshot workflows/activities."""
    async with Worker(
        temporal_client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[RunWorkflow],
        activities=[
            create_snapshot_job_activity,
            run_snapshot_activity,
            finish_snapshot_job_activity,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        yield  # allow the test to run while the worker is active
