import asyncio
from datetime import timedelta

from django.conf import settings
from django.db import connections, transaction

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
COMPLETION_TIMEOUT_SECONDS = 240


def billing_receive_batch_size(max_messages: int) -> int:
    # Serial completion waits must not consume another prefetched receipt's visibility lease.
    return 1 if get_entitlement_reactor_registry().reactors else max_messages


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


async def start_entitlement_reactions(organization_id: str, *, wait_for_completion: bool = False) -> None:
    async with asyncio.timeout(COMPLETION_TIMEOUT_SECONDS):
        async with asyncio.timeout(HANDOFF_TIMEOUT_SECONDS):
            client = await async_connect()
            handle = await client.start_workflow(
                EntitlementReactionsWorkflow.run,
                EntitlementReactionsInputs(organization_id=organization_id),
                id=f"entitlement-reactions-{organization_id}",
                task_queue=settings.BILLING_TASK_QUEUE,
                id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                start_signal=RESYNC_SIGNAL,
                execution_timeout=timedelta(hours=1),
            )
        if wait_for_completion:
            # Cancelling this RPC wait does not cancel the durable workflow.
            result = await handle.result()
            if result.failed_reactor_keys:
                raise RuntimeError(f"Entitlement reactors failed: {', '.join(result.failed_reactor_keys)}")


def _dispatch(organization_id: str, current: Entitlements, *, wait_for_completion: bool, enabled: bool | None) -> None:
    registry = get_entitlement_reactor_registry()
    if not registry.reactors or not (entitlement_reactions_enabled(organization_id) if enabled is None else enabled):
        return
    if get_behind_reactor_keys(organization_id, current, registry=registry):
        asyncio.run(start_entitlement_reactions(organization_id, wait_for_completion=wait_for_completion))


def dispatch_entitlement_reactions(
    organization_id: str, current: Entitlements, *, wait_for_completion: bool = False, enabled: bool | None = None
) -> None:
    """Dispatch committed source; strict callers must return only after required work completes."""
    if not get_entitlement_reactor_registry().reactors:
        return
    if wait_for_completion:
        if connections["default"].in_atomic_block:
            # An on_commit callback would acknowledge SQS before this transaction commits.
            raise RuntimeError("Cannot wait for entitlement reactions inside a transaction")
        _dispatch(organization_id, current, wait_for_completion=True, enabled=enabled)
        return

    def best_effort() -> None:
        try:
            _dispatch(organization_id, current, wait_for_completion=False, enabled=enabled)
        except Exception:
            logger.warning("entitlement_reactions_dispatch_failed", organization_id=organization_id, exc_info=True)

    transaction.on_commit(best_effort, using="default")
