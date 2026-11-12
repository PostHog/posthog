import uuid
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from unittest.mock import patch

from temporalio import activity, workflow
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization
from posthog.temporal.quota_limiting.run_quota_limiting import (
    SYNC_ENDED_BILLING_PERIODS_WORKFLOW_ID,
    QuotaLimitingResult,
    RunQuotaLimitingAllOrgsInputs,
    RunQuotaLimitingInputs,
    RunQuotaLimitingWorkflow,
    SyncEndedBillingPeriodsInputs,
    SyncEndedBillingPeriodsResult,
    SyncEndedBillingPeriodsWorkflow,
    sync_organizations_from_billing,
)


@pytest.fixture(autouse=True)
def _temporal_loggers_at_info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.activity")
    caplog.set_level(logging.INFO, logger="temporalio.workflow")


def test_sync_keeps_going_after_an_organization_fails() -> None:
    with patch(
        "posthog.temporal.quota_limiting.run_quota_limiting.sync_organization_from_billing",
        side_effect=[None, RuntimeError("billing is down"), Organization.DoesNotExist(), None],
    ):
        result = sync_organizations_from_billing(["org-a", "org-b", "org-deleted", "org-c"], min_interval_s=0)

    assert result == SyncEndedBillingPeriodsResult(synced=2, failed=1)


@workflow.defn(name="sync-ended-billing-periods")
class _RunningBillingSync:
    def __init__(self) -> None:
        self._released = False

    @workflow.run
    async def run(self, inputs: SyncEndedBillingPeriodsInputs) -> list[str]:
        await workflow.wait_condition(lambda: self._released)
        return inputs.organization_ids

    @workflow.signal
    def release(self) -> None:
        self._released = True


def _quota_run_ending(ended_period_org_ids: list[str]):
    @activity.defn(name="run-quota-limiting-all-orgs")
    async def quota_run(_inputs: RunQuotaLimitingAllOrgsInputs) -> QuotaLimitingResult:
        return QuotaLimitingResult(orgs_processed=3, ended_period_org_ids=ended_period_org_ids)

    return quota_run


@asynccontextmanager
async def _worker(sync_workflow: type, activities: list) -> AsyncIterator[tuple[WorkflowEnvironment, str]]:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[RunQuotaLimitingWorkflow, sync_workflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            yield env, task_queue


async def _run_quota_limiting(client: Client, task_queue: str) -> QuotaLimitingResult:
    return await client.execute_workflow(
        RunQuotaLimitingWorkflow.run,
        RunQuotaLimitingInputs(),
        id=str(uuid.uuid4()),
        task_queue=task_queue,
        execution_timeout=timedelta(minutes=5),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("ended_period_org_ids", [["org-a", "org-b"], []])
async def test_quota_run_hands_ended_periods_to_one_billing_sync(ended_period_org_ids: list[str]) -> None:
    synced: list[list[str]] = []

    @activity.defn(name="sync-ended-billing-periods")
    async def sync_activity(inputs: SyncEndedBillingPeriodsInputs) -> SyncEndedBillingPeriodsResult:
        synced.append(inputs.organization_ids)
        return SyncEndedBillingPeriodsResult(synced=len(inputs.organization_ids), failed=0)

    async with _worker(SyncEndedBillingPeriodsWorkflow, [_quota_run_ending(ended_period_org_ids), sync_activity]) as (
        env,
        task_queue,
    ):
        await _run_quota_limiting(env.client, task_queue)
        sync_handle = env.client.get_workflow_handle(SYNC_ENDED_BILLING_PERIODS_WORKFLOW_ID)

        if ended_period_org_ids:
            await sync_handle.result()
            assert synced == [ended_period_org_ids]
        else:
            with pytest.raises(RPCError) as error:
                await sync_handle.describe()
            assert error.value.status == RPCStatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_quota_run_succeeds_while_the_previous_billing_sync_runs() -> None:
    async with _worker(_RunningBillingSync, [_quota_run_ending(["org-new"])]) as (env, task_queue):
        # Skipping time would time out the idle sync while the quota run executes.
        with env.auto_time_skipping_disabled():
            running_sync = await env.client.start_workflow(
                _RunningBillingSync.run,
                SyncEndedBillingPeriodsInputs(organization_ids=["org-earlier"]),
                id=SYNC_ENDED_BILLING_PERIODS_WORKFLOW_ID,
                task_queue=task_queue,
            )

            result = await _run_quota_limiting(env.client, task_queue)
            await running_sync.signal(_RunningBillingSync.release)

            assert result.orgs_processed == 3
            assert await running_sync.result() == ["org-earlier"]
