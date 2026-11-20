import asyncio
from datetime import timedelta

from django.conf import settings
from django.db import transaction

import structlog
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.entitlements.contracts import Entitlements
from posthog.entitlements.execution import get_behind_reactor_keys
from posthog.entitlements.registry import get_entitlement_reactor_registry
from posthog.ph_client import feature_enabled_or_false
from posthog.temporal.common.client import async_connect
from posthog.temporal.entitlement_reactions.contracts import EntitlementReactionsInputs
from posthog.temporal.entitlement_reactions.workflow import RESYNC_SIGNAL, EntitlementReactionsWorkflow

logger = structlog.get_logger(__name__)
HANDOFF_TIMEOUT_SECONDS = 5


def entitlement_reactions_enabled(organization_id: str, *, fail_on_error: bool = True) -> bool:
    if not get_entitlement_reactor_registry().reactors:
        return False
    try:
        return feature_enabled_or_false(
            "billing-entitlement-reactions",
            organization_id,
            groups={"organization": organization_id},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        if fail_on_error:
            raise
        logger.warning("entitlement_reactions_flag_failed", organization_id=organization_id, exc_info=True)
        return False


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
    organization_id: str, current: Entitlements, *, watched_value_changed: bool, enabled: bool | None
) -> None:
    registry = get_entitlement_reactor_registry()
    if not registry.reactors or not (entitlement_reactions_enabled(organization_id) if enabled is None else enabled):
        return
    if watched_value_changed or get_behind_reactor_keys(organization_id, current, registry=registry):
        asyncio.run(start_entitlement_reactions(organization_id))


def dispatch_entitlement_reactions(
    organization_id: str,
    current: Entitlements,
    *,
    watched_value_changed: bool = False,
    enabled: bool | None = None,
) -> None:
    """Hand off after the default-database commit, best effort; the repair schedule retries a failed handoff."""
    if not get_entitlement_reactor_registry().reactors:
        return

    def best_effort() -> None:
        try:
            _dispatch(organization_id, current, watched_value_changed=watched_value_changed, enabled=enabled)
        except Exception:
            logger.warning("entitlement_reactions_dispatch_failed", organization_id=organization_id, exc_info=True)

    transaction.on_commit(best_effort, using="default")
