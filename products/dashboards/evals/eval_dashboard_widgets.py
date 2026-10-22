from __future__ import annotations

from typing import Any

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.dashboards.backend.models.dashboard_widget import DashboardWidget
from products.dashboards.backend.widget_specs.registry import validate_widget_config
from products.dashboards.evals.offline_config import offline_suite
from products.dashboards.evals.scorers import SavedWidgetState, WidgetFirstWriteValid
from products.posthog_ai.eval_harness.base import SandboxedPrivateEval
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

NO_SEND_LOGS = True

DASHBOARD_NAME = "Release health"
ERROR_TRACKING_WIDGET = "error_tracking_list"
LOGS_WIDGET = "logs_list"
SEEDED_ERROR_TRACKING_CONFIG: dict[str, Any] = {"limit": 5, "orderBy": "last_seen", "status": "active"}


def seed_empty_dashboard(context: CustomPromptSandboxContext) -> dict[str, Any]:
    if Dashboard.objects.filter(team_id=context.team_id, name=DASHBOARD_NAME, deleted=False).exists():
        raise ValueError("Dashboard widget eval requires an unused dashboard name")
    dashboard = Dashboard.objects.create(team_id=context.team_id, name=DASHBOARD_NAME)
    return {"team_id": context.team_id, "dashboard_id": dashboard.id}


def seed_error_tracking_widget(context: CustomPromptSandboxContext) -> dict[str, Any]:
    seed = seed_empty_dashboard(context)
    config = validate_widget_config(ERROR_TRACKING_WIDGET, SEEDED_ERROR_TRACKING_CONFIG)
    widget = DashboardWidget.objects.for_team(context.team_id).create(
        team_id=context.team_id, widget_type=ERROR_TRACKING_WIDGET, config=config
    )
    DashboardTile.objects.create(
        dashboard_id=seed["dashboard_id"], widget=widget, layouts={"sm": {"x": 0, "y": 0, "w": 6, "h": 5}}
    )
    return {**seed, "widget_id": str(widget.id), "widget_config": config}


async def eval_dashboard_widgets(ctx: EvalContext) -> None:
    await SandboxedPrivateEval(
        no_send_logs=NO_SEND_LOGS,
        experiment_name="sandboxed-dashboards-widgets-cli",
        offline_suite=offline_suite(
            "dashboards/eval_dashboard_widgets::eval_dashboard_widgets",
            metrics=["saved_widget_state", "widget_first_write_valid"],
        ),
        send_to_posthog=True,
        cases=[
            SandboxedEvalCase(
                name="add_error_tracking_widget",
                prompt=(
                    f"Add an error tracking widget to the existing '{DASHBOARD_NAME}' dashboard. "
                    "It should list the 15 resolved issues that affected the most users."
                ),
                setup=seed_empty_dashboard,
                expected={
                    "saved_widget_state": {
                        "widget_type": ERROR_TRACKING_WIDGET,
                        "config": {"limit": 15, "orderBy": "users", "status": "resolved"},
                    }
                },
            ),
            SandboxedEvalCase(
                name="add_logs_widget",
                prompt=(
                    f"Add a logs widget to the existing '{DASHBOARD_NAME}' dashboard. "
                    "It should show only error and fatal logs from the 'api' service, oldest first."
                ),
                setup=seed_empty_dashboard,
                expected={
                    "saved_widget_state": {
                        "widget_type": LOGS_WIDGET,
                        "config": {
                            "severityLevels": ["error", "fatal"],
                            "serviceNames": ["api"],
                            "orderBy": "earliest",
                        },
                    }
                },
            ),
            SandboxedEvalCase(
                name="update_error_tracking_widget",
                prompt=(
                    f"On the '{DASHBOARD_NAME}' dashboard, change the error tracking widget to show 20 issues. "
                    "Keep its other settings as they are."
                ),
                setup=seed_error_tracking_widget,
                expected={
                    "saved_widget_state": {
                        "widget_type": ERROR_TRACKING_WIDGET,
                        "config": {"limit": 20},
                        "preserved": ["orderBy", "status"],
                    }
                },
            ),
            SandboxedEvalCase(
                name="resize_error_tracking_widget",
                prompt=(
                    f"On the '{DASHBOARD_NAME}' dashboard, make the error tracking widget full width. "
                    "Do not change what it shows."
                ),
                setup=seed_error_tracking_widget,
                expected={
                    "saved_widget_state": {
                        "widget_type": ERROR_TRACKING_WIDGET,
                        "preserved": "all",
                        "layout_width": 12,
                    }
                },
            ),
        ],
        scorers=[SavedWidgetState(), WidgetFirstWriteValid()],
        ctx=ctx,
    )
