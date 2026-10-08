from __future__ import annotations

from typing import Any

from posthog.utils import generate_short_id

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.evals.scorers import SavedDashboardContents
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.product_analytics.backend.facade.api import get_or_create_saved_insight
from products.product_analytics.backend.facade.models import Insight
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

DASHBOARD_NAME = "File activity overview"
SIGNUPS_NAME = "Saved daily signups"
UPLOADS_NAME = "Saved daily file uploads"


def seed_saved_insights(context: CustomPromptSandboxContext) -> dict[str, Any]:
    if Dashboard.objects.for_team(context.team_id).filter(name=DASHBOARD_NAME, deleted=False).exists():
        raise ValueError("Dashboard eval requires an unused name")
    insights: dict[str, dict[str, object]] = {}
    for name, event in [(SIGNUPS_NAME, "signed_up"), (UPLOADS_NAME, "uploaded_file")]:
        query: dict[str, object] = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": event, "math": "total"}],
            "dateRange": {"date_from": "-30d"},
            "interval": "day",
        }
        insight_id, _ = get_or_create_saved_insight(
            team_id=context.team_id,
            user_id=context.user_id,
            short_id=generate_short_id(),
            name=name,
            description=None,
            query=query,
        )
        insights[str(insight_id)] = query
    return {
        "team_id": context.team_id,
        "insights": insights,
        "initial_insight_ids": list(Insight.objects.for_team(context.team_id).values_list("id", flat=True)),
        "initial_dashboard_ids": list(
            Dashboard.objects.for_team(context.team_id).filter(deleted=False).values_list("id", flat=True)
        ),
    }


def seed_existing_dashboard(context: CustomPromptSandboxContext) -> dict[str, Any]:
    seed = seed_saved_insights(context)
    dashboard = Dashboard.objects.create(team_id=context.team_id, name=DASHBOARD_NAME)
    tile = DashboardTile.objects.create(
        dashboard=dashboard,
        insight_id=int(next(iter(seed["insights"]))),
        layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}},
    )
    return {
        **seed,
        "dashboard_id": dashboard.id,
        "original_tile_id": tile.id,
        "original_tile_insight_id": tile.insight_id,
    }


async def eval_dashboard_contents(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        experiment_name="sandboxed-dashboards-saved-contents-cli",
        cases=[
            SandboxedEvalCase(
                name="create_from_saved_insights",
                prompt=(
                    f"Create a dashboard named '{DASHBOARD_NAME}' with exactly these two saved insights: "
                    f"'{SIGNUPS_NAME}' and '{UPLOADS_NAME}'. Reuse the saved insights without changing their queries."
                ),
                setup=seed_saved_insights,
                expected={"saved_dashboard_contents": {"name": DASHBOARD_NAME}},
            ),
            SandboxedEvalCase(
                name="add_insight_preserving_existing_chart",
                prompt=(
                    f"Add the saved insight '{UPLOADS_NAME}' to the existing '{DASHBOARD_NAME}' dashboard. "
                    f"Keep its existing '{SIGNUPS_NAME}' chart. Reuse the saved insights without changing their queries."
                ),
                setup=seed_existing_dashboard,
                expected={"saved_dashboard_contents": {"name": DASHBOARD_NAME}},
            ),
        ],
        scorers=[SavedDashboardContents()],
        ctx=ctx,
    )
