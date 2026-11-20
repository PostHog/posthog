from datetime import timedelta

from temporalio import activity, common, workflow
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from posthog.dataclasses import frozen
    from posthog.entitlements.dispatch import entitlement_reactions_enabled, start_entitlement_reactions
    from posthog.entitlements.repair import BehindOrganizationsPage, list_behind_organizations_page
    from posthog.sync import database_sync_to_async_pool
    from posthog.temporal.common.base import PostHogWorkflow


MAX_PAGES_PER_RUN = 20


@frozen
class EntitlementRepairInputs:
    after: str | None = None


@activity.defn(name="list-behind-entitlement-organizations")
async def list_behind_entitlement_organizations_activity(inputs: EntitlementRepairInputs) -> BehindOrganizationsPage:
    return await database_sync_to_async_pool(list_behind_organizations_page)(inputs.after)


@activity.defn(name="dispatch-entitlement-repair")
async def dispatch_entitlement_repair_activity(organization_id: str) -> None:
    if await database_sync_to_async_pool(entitlement_reactions_enabled)(organization_id):
        await start_entitlement_reactions(organization_id)


@workflow.defn(name="repair-entitlement-reactions")
class EntitlementRepairWorkflow(PostHogWorkflow):
    inputs_cls = EntitlementRepairInputs

    @workflow.run
    async def run(self, inputs: EntitlementRepairInputs) -> None:
        pages = 0
        while True:
            page = await workflow.execute_activity(
                list_behind_entitlement_organizations_activity,
                inputs,
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(minutes=2),
                retry_policy=common.RetryPolicy(maximum_attempts=3),
            )
            for organization_id in page.organization_ids:
                # Sleep before each dispatch, including page boundaries and continuations.
                await workflow.sleep(timedelta(milliseconds=100))
                try:
                    await workflow.execute_activity(
                        dispatch_entitlement_repair_activity,
                        organization_id,
                        start_to_close_timeout=timedelta(seconds=10),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=common.RetryPolicy(maximum_attempts=1),
                    )
                except ActivityError:
                    # No checkpoint advances on failed handoff; the next sweep finds it again.
                    workflow.logger.warning(
                        "Entitlement repair handoff failed", extra={"organization_id": organization_id}
                    )
            if page.cursor is None:
                return
            inputs = EntitlementRepairInputs(after=page.cursor)
            pages += 1
            if pages >= MAX_PAGES_PER_RUN or workflow.info().is_continue_as_new_suggested():
                workflow.continue_as_new(inputs)
