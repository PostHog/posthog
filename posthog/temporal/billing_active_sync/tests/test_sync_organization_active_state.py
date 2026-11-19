import uuid

import pytest

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.billing_active_sync.sync_organization_active_state import (
    RESYNC_SIGNAL,
    SyncOrganizationActiveStateInputs,
    SyncOrganizationActiveStateWorkflow,
)


async def _run_sync_workflow(signals_during_first_sync: int) -> int:
    calls: list[str] = []
    workflow_id = str(uuid.uuid4())
    client: Client | None = None

    @activity.defn(name="sync-organization-active-state")
    async def stub_sync(inputs: SyncOrganizationActiveStateInputs) -> None:
        calls.append(inputs.organization_id)
        if len(calls) == 1:
            assert client is not None
            handle = client.get_workflow_handle(workflow_id)
            for _ in range(signals_during_first_sync):
                await handle.signal(RESYNC_SIGNAL)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = env.client
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[SyncOrganizationActiveStateWorkflow],
            activities=[stub_sync],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            handle = await env.client.start_workflow(
                SyncOrganizationActiveStateWorkflow.run,
                SyncOrganizationActiveStateInputs(organization_id="org-1"),
                id=workflow_id,
                task_queue=task_queue,
                start_signal=RESYNC_SIGNAL,
            )
            await handle.result()
    return len(calls)


class TestSyncOrganizationActiveStateWorkflow:
    @pytest.mark.asyncio
    async def test_syncs_once_without_a_flip_during_the_run(self) -> None:
        assert await _run_sync_workflow(signals_during_first_sync=0) == 1

    @pytest.mark.asyncio
    async def test_flips_during_a_run_cause_exactly_one_more_sync(self) -> None:
        assert await _run_sync_workflow(signals_during_first_sync=3) == 2
