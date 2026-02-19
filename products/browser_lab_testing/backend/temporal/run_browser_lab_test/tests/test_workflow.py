import uuid

import pytest

import temporalio.worker
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.browser_lab_testing.backend.models import BrowserLabTest, BrowserLabTestRun
from products.browser_lab_testing.backend.temporal.run_browser_lab_test.activities import run_browser_lab_test_activity
from products.browser_lab_testing.backend.temporal.run_browser_lab_test.workflow import (
    RunBrowserLabTestWorkflow,
    RunBrowserLabTestWorkflowInput,
)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_workflow_completes_run(team):
    lab_test = await BrowserLabTest.objects.acreate(
        team=team,
        name="Test",
        url="https://example.com",
        steps=[],
    )
    lab_test_run = await BrowserLabTestRun.objects.acreate(
        browser_lab_test=lab_test,
        status=BrowserLabTestRun.Status.PENDING,
    )

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RunBrowserLabTestWorkflow],
            activities=[run_browser_lab_test_activity],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                RunBrowserLabTestWorkflow.run,
                RunBrowserLabTestWorkflowInput(
                    team_id=team.id,
                    browser_lab_test_id=str(lab_test.id),
                    browser_lab_test_run_id=str(lab_test_run.id),
                ),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert result.success is True
    assert result.error is None

    await lab_test_run.arefresh_from_db()
    assert lab_test_run.status == BrowserLabTestRun.Status.COMPLETED
    assert lab_test_run.finished_at is not None
