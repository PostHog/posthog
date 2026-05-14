"""Agent description-pass activities.

Three activities run after the deterministic phase finishes:

  - spawn_catalog_agent_task — creates a `products/tasks/` Task + TaskRun and
    starts the ProcessTaskWorkflow in the background. Returns the task_run_id.
  - wait_for_task_run_completion — watches the agent's redis event stream and
    signals `complete_task` on the first `end_turn`, then polls TaskRun.status
    until terminal. Returns the final status.
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

import structlog
from temporalio import activity

from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.oauth import MCP_READ_SCOPES

from products.catalog.backend.models import CatalogColumn, CatalogNode
from products.catalog.backend.temporal.agent_prompts import CATALOG_DESCRIPTION_SYSTEM_PROMPT
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.stream.redis_stream import TaskRunRedisStream, TaskRunStreamError

from ee.hogai.sandbox import is_turn_complete

logger = structlog.get_logger(__name__)

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
        posthog_mcp_scopes=[*MCP_READ_SCOPES, "catalog:write"],
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
    """Wait for the agent task to reach a terminal state.

    The agent never explicitly tells ProcessTaskWorkflow it's done — that
    workflow's main loop only exits on a `complete_task` signal or its 2h
    inactivity timeout. We bridge the gap: subscribe to the run's redis event
    stream, fire `complete_task` on the first `end_turn`, then poll TaskRun
    until terminal. Without the signal the activity would always time out.
    """
    async with Heartbeater():
        task_run = await asyncio.to_thread(_load_task_run, task_run_id)
        workflow_id = TaskRun.get_workflow_id(str(task_run.task_id), task_run_id)
        await _signal_complete_on_end_turn(task_run_id, workflow_id)
        return await _poll_until_terminal(task_run_id)


async def _signal_complete_on_end_turn(task_run_id: str, workflow_id: str) -> None:
    """Subscribe to the agent stream; signal complete_task on first end_turn.

    `end_turn` is the ACP model's "I have no more output to generate" marker.
    It only fires when the model finishes its final assistant message — never
    while a tool call is in flight, because the model resumes generating after
    each tool result and only emits `end_turn` once it has nothing more to say.

    What this means for our exit signal:

      - **Happy path**: agent runs tool calls, writes descriptions, emits a
        final summary, end_turn → we signal complete with `status="completed"`.
      - **Agent gives up**: model decides the task can't be done (e.g., it
        couldn't find a needed tool) and writes an explanation; that final
        message ends with end_turn just the same. We still signal complete.
      - **Mid-tool-call**: cannot happen — no end_turn until the model's
        post-tool reply finishes.

    So `end_turn` means "agent is done generating", not "agent succeeded".
    That distinction is fine here because the catalog workflow's
    `count_descriptions_for_run` measures success independently — a no-op
    agent run shows up as `descriptions=0` on the traversal run, while a
    real failure (tool error, network blip) surfaces as a non-`completed`
    TaskRun status from ProcessTaskWorkflow's own error path.
    """
    stream = TaskRunRedisStream(task_run_id)
    try:
        async for event in stream.read_stream(start_id="0", block_ms=1000, keepalive_interval_seconds=30):
            if event is None:
                continue
            if is_turn_complete(event):
                client = await async_connect()
                await client.get_workflow_handle(workflow_id).signal("complete_task", "completed")
                logger.info("catalog_agent_complete_signaled", run_id=task_run_id, workflow_id=workflow_id)
                return
    except TaskRunStreamError as exc:
        # Stream gone / expired / completed — TaskRun is likely already terminal.
        # Let _poll_until_terminal observe the final state.
        logger.info("catalog_agent_stream_ended", run_id=task_run_id, reason=str(exc))


async def _poll_until_terminal(task_run_id: str) -> str:
    while True:
        status = await asyncio.to_thread(_read_task_run_status, task_run_id)
        if status in _TERMINAL_STATUSES:
            return status
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


def _load_task_run(task_run_id: str) -> TaskRun:
    return TaskRun.objects.only("id", "task_id").get(id=task_run_id)


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
