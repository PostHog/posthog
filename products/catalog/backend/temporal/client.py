"""Helpers for starting CatalogTraversalWorkflow from outside Temporal.

Useful for manual triggers (Django shell, future POST endpoint, signal
handlers). Schedule and signal wiring land in a later commit; this module is
the lowest-level entry point both will eventually go through.
"""

from django.conf import settings

from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from posthog.temporal.common.client import async_connect

from products.catalog.backend.temporal.constants import WORKFLOW_ID_PREFIX
from products.catalog.backend.temporal.workflow import (
    CatalogTraversalInputs,
    CatalogTraversalResult,
    CatalogTraversalWorkflow,
)


def workflow_id_for_team(team_id: int) -> str:
    """Stable workflow id per team. Lets `REJECT_DUPLICATE` debounce re-triggers."""
    return f"{WORKFLOW_ID_PREFIX}-{team_id}"


async def execute_catalog_traversal_workflow_async(
    team_id: int,
    *,
    trigger: str = "manual",
    generator_model: str | None = None,
) -> CatalogTraversalResult:
    """Run a catalog traversal end-to-end and return its result.

    Blocks the caller until the workflow completes. For fire-and-forget use,
    swap `execute_workflow` for `start_workflow` and return the handle.
    """
    client = await async_connect()
    return await client.execute_workflow(
        CatalogTraversalWorkflow.run,
        CatalogTraversalInputs(
            team_id=team_id,
            trigger=trigger,
            generator_model=generator_model,
        ),
        id=workflow_id_for_team(team_id),
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
    )


async def start_catalog_traversal_workflow_async(
    team_id: int,
    *,
    trigger: str = "manual",
    generator_model: str | None = None,
) -> str:
    """Kick off a catalog traversal asynchronously and return the workflow id.

    Used by the POST /catalog/sync/ endpoint — returns immediately so the HTTP
    request doesn't block on the multi-minute agent passes. If a run is already
    in-flight for this team, `USE_EXISTING` returns a handle to it rather than
    raising — the sync button stays idempotent.
    """
    client = await async_connect()
    handle = await client.start_workflow(
        CatalogTraversalWorkflow.run,
        CatalogTraversalInputs(
            team_id=team_id,
            trigger=trigger,
            generator_model=generator_model,
        ),
        id=workflow_id_for_team(team_id),
        task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    return handle.id
