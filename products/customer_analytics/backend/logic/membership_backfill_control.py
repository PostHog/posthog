from django.conf import settings

from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.customer_analytics.backend.logic.membership_backfill import MembershipTeam
from products.customer_analytics.backend.temporal.membership_backfill import (
    MembershipBackfillWorkflow,
    MembershipRunStatus,
    get_membership_workflow_id,
)


class MembershipBackfillControl:
    def __init__(self, client: Client) -> None:
        self.client = client

    @classmethod
    async def connect(cls) -> "MembershipBackfillControl":
        return cls(await async_connect())

    async def start(self, team_id: int, *, account_keys: tuple[str, ...], dry_run: bool) -> str:
        handle = await self.client.start_workflow(
            MembershipBackfillWorkflow.run,
            MembershipTeam(team_id=team_id, account_keys=account_keys, dry_run=dry_run),
            id=get_membership_workflow_id(team_id),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        return handle.first_execution_run_id or ""

    async def get_status(self, team_id: int) -> MembershipRunStatus:
        handle = self.client.get_workflow_handle(get_membership_workflow_id(team_id))
        return await handle.query(MembershipBackfillWorkflow.get_status)

    async def resume(self, team_id: int) -> None:
        status = await self.get_status(team_id)
        if status.status != "failed":
            raise ValueError("Only a failed backfill can resume")
        handle = self.client.get_workflow_handle(get_membership_workflow_id(team_id))
        await handle.signal(MembershipBackfillWorkflow.resume)

    async def cancel(self, team_id: int) -> None:
        handle = self.client.get_workflow_handle(get_membership_workflow_id(team_id))
        await handle.signal(MembershipBackfillWorkflow.cancel)
