from django.conf import settings

from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.customer_analytics.backend.facade.membership_snapshot_contracts import (
    MembershipSnapshotInput,
    MembershipSnapshotStatus,
)
from products.customer_analytics.backend.temporal.membership_snapshot_backfill import (
    MembershipSnapshotBackfillWorkflow,
    check_membership_writers_paused,
    get_membership_snapshot_workflow_id,
)


async def start_membership_snapshot(input: MembershipSnapshotInput) -> str:
    if not input.dry_run:
        await check_membership_writers_paused(input.team_id)
    client = await async_connect()
    handle = await client.start_workflow(
        MembershipSnapshotBackfillWorkflow.run,
        input,
        id=get_membership_snapshot_workflow_id(input.team_id),
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    return handle.first_execution_run_id or ""


async def get_membership_snapshot_status(team_id: int) -> MembershipSnapshotStatus:
    client = await async_connect()
    return await client.get_workflow_handle(get_membership_snapshot_workflow_id(team_id)).query(
        MembershipSnapshotBackfillWorkflow.get_status
    )


async def resume_membership_snapshot(team_id: int) -> None:
    if (await get_membership_snapshot_status(team_id)).status != "failed":
        raise ValueError("Only a failed snapshot backfill can resume")
    client = await async_connect()
    await client.get_workflow_handle(get_membership_snapshot_workflow_id(team_id)).signal(
        MembershipSnapshotBackfillWorkflow.resume
    )


async def cancel_membership_snapshot(team_id: int) -> None:
    client = await async_connect()
    await client.get_workflow_handle(get_membership_snapshot_workflow_id(team_id)).signal(
        MembershipSnapshotBackfillWorkflow.cancel
    )
