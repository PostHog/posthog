from temporalio import activity

from posthog.entitlements.execution import ReactorExecutionResult, execute_entitlement_reactor, list_behind_reactor_keys
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.entitlement_reactions.contracts import EntitlementReactionsInputs, ExecuteEntitlementReactorInputs


@activity.defn(name="list-behind-entitlement-reactors")
async def list_behind_entitlement_reactors_activity(inputs: EntitlementReactionsInputs) -> list[str]:
    return await database_sync_to_async_pool(list_behind_reactor_keys)(inputs.organization_id)


@activity.defn(name="execute-entitlement-reactor")
async def execute_entitlement_reactor_activity(inputs: ExecuteEntitlementReactorInputs) -> ReactorExecutionResult:
    return await database_sync_to_async_pool(execute_entitlement_reactor)(inputs.organization_id, inputs.reactor_key)
