import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

import temporalio.worker
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from products.browser_lab_testing.backend.models import BrowserLabTest, BrowserLabTestRun
from products.browser_lab_testing.backend.temporal.run_browser_lab_test.activities import (
    fetch_browser_lab_test_activity,
    run_browser_lab_test_activity,
)
from products.browser_lab_testing.backend.temporal.run_browser_lab_test.workflow import (
    RunBrowserLabTestWorkflow,
    RunBrowserLabTestWorkflowInput,
)

ACTIVITIES = [fetch_browser_lab_test_activity, run_browser_lab_test_activity]


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
            activities=ACTIVITIES,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=4),
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
    assert lab_test_run.result is not None
    assert "page_title" in lab_test_run.result


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_workflow_resolves_secret_placeholders(team):
    lab_test = await BrowserLabTest.objects.acreate(
        team=team,
        name="Test with secrets",
        url="https://example.com",
        steps=[{"action": "type", "selector": "#password", "text": "{{secrets.PASSWORD}}"}],
        encrypted_secrets={"PASSWORD": "hunter2"},
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
            activities=ACTIVITIES,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=4),
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

    await lab_test_run.arefresh_from_db()
    assert lab_test_run.status == BrowserLabTestRun.Status.COMPLETED


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
@pytest.mark.playwright
async def test_workflow_visits_posthog_com(team):
    lab_test = await BrowserLabTest.objects.acreate(
        team=team,
        name="Visit PostHog",
        url="https://posthog.com",
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
            activities=ACTIVITIES,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
            activity_executor=ThreadPoolExecutor(max_workers=4),
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
    assert lab_test_run.result is not None
    assert "PostHog" in lab_test_run.result["page_title"]
    assert "posthog.com" in lab_test_run.result["final_url"]
