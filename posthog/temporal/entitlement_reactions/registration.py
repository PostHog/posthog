from collections.abc import Awaitable, Callable

from posthog.temporal.entitlement_reactions.activities import (
    execute_entitlement_reactor_activity,
    list_behind_entitlement_reactors_activity,
)
from posthog.temporal.entitlement_reactions.repair import (
    EntitlementRepairWorkflow,
    dispatch_entitlement_repair_activity,
    list_behind_entitlement_organizations_activity,
)
from posthog.temporal.entitlement_reactions.workflow import EntitlementReactionsWorkflow

WORKFLOWS = [EntitlementReactionsWorkflow, EntitlementRepairWorkflow]
ACTIVITIES: list[Callable[..., Awaitable[object]]] = [
    list_behind_entitlement_reactors_activity,
    execute_entitlement_reactor_activity,
    list_behind_entitlement_organizations_activity,
    dispatch_entitlement_repair_activity,
]
