import asyncio
from datetime import timedelta

from django.conf import settings
from django.db import transaction

import structlog
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.entitlements.contracts import Entitlements
from posthog.entitlements.execution import get_behind_reactor_keys
from posthog.entitlements.flags import enabled_reactor_keys
from posthog.entitlements.registry import get_entitlement_reactor_registry
from posthog.temporal.common.client import async_connect
from posthog.temporal.entitlement_reactions.contracts import EntitlementReactionsInputs
from posthog.temporal.entitlement_reactions.workflow import RESYNC_SIGNAL, EntitlementReactionsWorkflow

logger = structlog.get_logger(__name__)
HANDOFF_TIMEOUT_SECONDS = 5


async def start_entitlement_reactions(organization_id: str) -> None:
    async with asyncio.timeout(HANDOFF_TIMEOUT_SECONDS):
        client = await async_connect()
        await client.start_workflow(
            EntitlementReactionsWorkflow.run,
            EntitlementReactionsInputs(organization_id=organization_id),
            id=f"entitlement-reactions-{organization_id}",
            task_queue=settings.BILLING_TASK_QUEUE,
            id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            start_signal=RESYNC_SIGNAL,
            execution_timeout=timedelta(hours=1),
        )


def _dispatch(
    organization_id: str,
    current: Entitlements,
    *,
    watched_value_changed: bool,
    enabled_reactors: frozenset[str] | None,
) -> None:
    registry = get_entitlement_reactor_registry()
    enabled = (
        enabled_reactors if enabled_reactors is not None else enabled_reactor_keys(organization_id, registry=registry)
    )
    if not enabled:
        return
    if watched_value_changed or not enabled.isdisjoint(
        get_behind_reactor_keys(organization_id, current, registry=registry)
    ):
        asyncio.run(start_entitlement_reactions(organization_id))


def dispatch_entitlement_reactions(
    organization_id: str,
    current: Entitlements,
    *,
    watched_value_changed: bool = False,
    enabled_reactors: frozenset[str] | None = None,
) -> None:
    """Hand off after the default-database commit, best effort; the repair schedule retries a failed handoff."""
    if not get_entitlement_reactor_registry().reactors or (enabled_reactors is not None and not enabled_reactors):
        return

    def best_effort() -> None:
        try:
            _dispatch(
                organization_id,
                current,
                watched_value_changed=watched_value_changed,
                enabled_reactors=enabled_reactors,
            )
        except Exception:
            logger.warning("entitlement_reactions_dispatch_failed", organization_id=organization_id, exc_info=True)

    transaction.on_commit(best_effort, using="default")
