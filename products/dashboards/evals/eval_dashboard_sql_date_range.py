from __future__ import annotations

from typing import Any

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.evals.offline_config import offline_suite
from products.dashboards.evals.scorers import SQLTilesFollowDashboardDateRange
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

NO_SEND_LOGS = True

SIGNUPS_DASHBOARD_NAME = "Signups and uploads (SQL)"
BILLING_DASHBOARD_NAME = "Billing and downloads (SQL)"


def seed_team(context: CustomPromptSandboxContext) -> dict[str, Any]:
    names = [SIGNUPS_DASHBOARD_NAME, BILLING_DASHBOARD_NAME]
    if Dashboard.objects.filter(team_id=context.team_id, name__in=names, deleted=False).exists():
        raise ValueError("Dashboard SQL date range eval requires unused names")
    return {"team_id": context.team_id}


async def eval_dashboard_sql_date_range(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        no_send_logs=NO_SEND_LOGS,
        experiment_name="sandboxed-dashboards-sql-date-range-cli",
        offline_suite=offline_suite(
            "dashboards/eval_dashboard_sql_date_range::eval_dashboard_sql_date_range",
            metrics=["sql_tiles_follow_dashboard_date_range"],
        ),
        send_to_posthog=True,
        cases=[
            SandboxedEvalCase(
                name="sql_tiles_without_date_hint",
                prompt=(
                    f"Create a dashboard named '{SIGNUPS_DASHBOARD_NAME}' with two SQL insights written in HogQL: "
                    "daily `signed_up` event counts, and `uploaded_file` event counts by the `file_type` property."
                ),
                setup=seed_team,
                expected={
                    "sql_tiles_follow_dashboard_date_range": {"name": SIGNUPS_DASHBOARD_NAME, "min_sql_tiles": 2}
                },
            ),
            SandboxedEvalCase(
                name="sql_tiles_with_last_30_days",
                prompt=(
                    f"Create a dashboard named '{BILLING_DASHBOARD_NAME}' for the last 30 days. "
                    "Add two SQL insights written in HogQL: the total `amount_usd` of `paid_bill` events by `plan`, "
                    "and daily unique users who triggered `downloaded_file`."
                ),
                setup=seed_team,
                expected={
                    "sql_tiles_follow_dashboard_date_range": {"name": BILLING_DASHBOARD_NAME, "min_sql_tiles": 2}
                },
            ),
        ],
        scorers=[SQLTilesFollowDashboardDateRange()],
        ctx=ctx,
    )
