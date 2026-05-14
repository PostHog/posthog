"""Agent metric-proposal-pass activities.

Phase 3 of the catalog traversal. Runs after Phase 2 (description pass) so the
metric agent has descriptions to read while reasoning about which queries on
the team's existing dashboards represent real business metrics.

Two new activities:

  - spawn_catalog_metric_proposal_task — creates a `products/tasks/` Task +
    TaskRun running the metric-proposal prompt and returns the task_run_id.
  - count_metrics_for_run — counts CatalogMetric rows the agent wrote during
    this traversal pass (for the audit counter on CatalogTraversalRun).

The third activity needed by the workflow — `wait_for_task_run_completion` —
is the same one Phase 2 uses; it's generic over agent passes and lives in
`agent.py`. The metric-proposal pass reuses it directly.

The agent itself runs inside the sandbox using the existing `@posthog/agent`
runtime. It reads what's already tracked via `dashboards-get-all`,
`insights-list`, `activity-log-list`, and HogQL against `app_metrics` /
`system.tables` (popularity + descriptions), and writes back via the
`catalog-metrics-create` MCP tool.
"""

import asyncio
from datetime import datetime

import structlog
from temporalio import activity

from posthog.models.team.team import Team
from posthog.temporal.oauth import MCP_READ_SCOPES

from products.catalog.backend.models import CatalogMetric
from products.catalog.backend.temporal.activities.agent import _resolve_catalog_task_user
from products.catalog.backend.temporal.agent_prompts import CATALOG_METRIC_PROPOSAL_SYSTEM_PROMPT
from products.tasks.backend.models import Task

logger = structlog.get_logger(__name__)


# --- spawn_catalog_metric_proposal_task --------------------------------------


@activity.defn
async def spawn_catalog_metric_proposal_task(team_id: int) -> str:
    """Create a Task + TaskRun for the metric-proposal pass and return the run id."""
    return await asyncio.to_thread(_spawn_catalog_metric_proposal_task_sync, team_id)


def _spawn_catalog_metric_proposal_task_sync(team_id: int) -> str:
    team = Team.objects.select_related("organization").get(id=team_id)
    user = _resolve_catalog_task_user(team)

    task = Task.create_and_run(
        team=team,
        title="Catalog metric proposal pass",
        # Prompt has JSON examples with literal `{`/`}`; use replace() with a
        # non-brace placeholder rather than .format() to avoid KeyError on them.
        description=CATALOG_METRIC_PROPOSAL_SYSTEM_PROMPT.replace("<<TEAM_ID>>", str(team_id)),
        origin_product=Task.OriginProduct.AUTOMATION,
        user_id=user.id,
        repository=None,
        create_pr=False,
        # Read access for dashboards/insights/activity-log/query; write access for
        # the new catalog-metrics-create tool. MCP_READ_SCOPES already covers all
        # read scopes (matches the "read_only" preset), so the agent can walk
        # `app_metrics` via execute-sql and resolve dashboard / insight names.
        posthog_mcp_scopes=[*MCP_READ_SCOPES, "catalog:write"],
    )
    run = task.runs.order_by("-created_at").first()
    if run is None:
        raise RuntimeError(f"Task {task.id} did not produce a TaskRun")
    return str(run.id)


# --- count_metrics_for_run ---------------------------------------------------


@activity.defn
async def count_metrics_for_run(team_id: int, started_at_iso: str) -> int:
    """Count CatalogMetric rows the agent created or updated during this pass."""
    started_at = datetime.fromisoformat(started_at_iso)
    return await asyncio.to_thread(_count_metrics_for_run_sync, team_id, started_at)


def _count_metrics_for_run_sync(team_id: int, started_at: datetime) -> int:
    # `updated_at` covers both new metrics (first insert auto_now_add=True so
    # updated_at == created_at) and re-upserts where the agent reasserted an
    # existing metric definition in this pass.
    return CatalogMetric.objects.filter(team_id=team_id, updated_at__gte=started_at).count()
