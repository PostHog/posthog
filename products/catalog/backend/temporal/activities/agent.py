"""Agent description-pass activities.

Three activities run after the deterministic phase finishes:

  - spawn_catalog_agent_task — creates a `products/tasks/` Task + TaskRun and
    starts the ProcessTaskWorkflow in the background. Returns the task_run_id.
  - wait_for_task_run_completion — polls TaskRun.status until terminal,
    heartbeating Temporal each iteration. Returns the final status.
  - count_descriptions_for_run — reads back how many node/column descriptions
    landed during this traversal pass for the audit counter.

The agent itself runs inside the sandbox using the existing `@posthog/agent`
runtime. It reads the catalog via HogQL `system.tables` / `system.columns` /
`system.relationships` (through the MCP `execute-sql` tool) and writes back
via the existing `catalog-nodes-create` / `catalog-columns-create` MCP tools.
No new MCP tools.
"""

import asyncio
from datetime import datetime

from temporalio import activity

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.heartbeat import Heartbeater

from products.catalog.backend.models import CatalogColumn, CatalogNode
from products.catalog.backend.temporal.agent_prompts import CATALOG_DESCRIPTION_SYSTEM_PROMPT
from products.tasks.backend.models import Task, TaskRun

_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {
        TaskRun.Status.COMPLETED,
        TaskRun.Status.FAILED,
        TaskRun.Status.CANCELLED,
    }
)

# Poll interval used by wait_for_task_run_completion. Short enough that workflow
# observability stays responsive; long enough not to hammer Postgres while the
# agent is slow-loading.
_POLL_INTERVAL_SECONDS = 15


# --- spawn_catalog_agent_task -------------------------------------------------


@activity.defn
async def spawn_catalog_agent_task(team_id: int) -> str:
    """Create a Task + TaskRun for the description pass and return the run id."""
    return await asyncio.to_thread(_spawn_catalog_agent_task_sync, team_id)


def _spawn_catalog_agent_task_sync(team_id: int) -> str:
    team = Team.objects.select_related("organization").get(id=team_id)
    user = _resolve_catalog_task_user(team)

    task = Task.create_and_run(
        team=team,
        title="Catalog description pass",
        description=CATALOG_DESCRIPTION_SYSTEM_PROMPT.format(team_id=team_id),
        origin_product=Task.OriginProduct.AUTOMATION,
        user_id=user.id,
        repository=None,
        create_pr=False,
        # catalog:read needed because system.tables/columns/relationships carry
        # access_scope="catalog" and HogQL filters them out without it.
        # query:read is for execute-sql itself.
        posthog_mcp_scopes=["catalog:read", "catalog:write", "query:read"],
    )
    run = task.runs.order_by("-created_at").first()
    if run is None:
        raise RuntimeError(f"Task {task.id} did not produce a TaskRun")
    return str(run.id)


def _resolve_catalog_task_user(team: Team) -> User:
    """Pick a user to attribute the catalog agent task to.

    System-initiated traversal has no real user, so we mirror the convention
    other auto-started tasks use: pick a high-privilege organization member.
    Owner first (level=15), then admin (level=8). Raises if neither exists —
    every active team should have at least one of these.
    """
    membership = (
        OrganizationMembership.objects.filter(
            organization_id=team.organization_id,
            level__gte=OrganizationMembership.Level.ADMIN,
        )
        .select_related("user")
        .order_by("-level", "joined_at")
        .first()
    )
    if membership is None:
        raise RuntimeError(f"Team {team.id} has no org admin/owner to attribute the catalog task to")
    return membership.user


# --- wait_for_task_run_completion ---------------------------------------------


@activity.defn
async def wait_for_task_run_completion(task_run_id: str) -> str:
    """Poll TaskRun.status until terminal. Heartbeats every poll.

    Activity-level timeout (set in the workflow via start_to_close_timeout) is
    the hard wall-clock cap. If it expires before the agent finishes, Temporal
    fails the activity with TimeoutError — workflow's except clause runs
    fail_traversal_run.
    """
    async with Heartbeater():
        while True:
            status = await asyncio.to_thread(_read_task_run_status, task_run_id)
            if status in _TERMINAL_STATUSES:
                return status
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def _read_task_run_status(task_run_id: str) -> str:
    return TaskRun.objects.values_list("status", flat=True).get(id=task_run_id)


# --- count_descriptions_for_run -----------------------------------------------


@activity.defn
async def count_descriptions_for_run(team_id: int, started_at_iso: str) -> int:
    """Count nodes + columns whose synthetic_description was set during this run."""
    started_at = datetime.fromisoformat(started_at_iso)
    return await asyncio.to_thread(_count_descriptions_for_run_sync, team_id, started_at)


def _count_descriptions_for_run_sync(team_id: int, started_at: datetime) -> int:
    node_count = CatalogNode.objects.filter(
        team_id=team_id,
        synthetic_description__isnull=False,
        description_generated_at__gte=started_at,
    ).count()
    column_count = CatalogColumn.objects.filter(
        team_id=team_id,
        synthetic_description__isnull=False,
        description_generated_at__gte=started_at,
    ).count()
    return node_count + column_count
