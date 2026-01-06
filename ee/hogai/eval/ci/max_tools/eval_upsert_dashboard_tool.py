from typing import Any

import pytest
from unittest.mock import patch

from braintrust import EvalCase

from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.eval.scorers import DangerousOperationAccuracy
from ee.hogai.tools.upsert_dashboard import UpsertDashboardTool
from ee.hogai.tools.upsert_dashboard.tool import CreateDashboardToolArgs, UpdateDashboardToolArgs, UpsertDashboardAction


@pytest.mark.django_db
async def eval_upsert_dashboard_dangerous_operation(pytestconfig, dashboard_with_insights):
    """
    Test that dangerous operations correctly trigger the approval flow.
    """

    async def task_check_dangerous(args: dict[str, Any]) -> dict[str, Any]:
        with patch(
            "ee.hogai.utils.feature_flags.has_upsert_dashboard_feature_flag",
            return_value=True,
        ):
            action: UpsertDashboardAction
            if args.get("action") == "update":
                action = UpdateDashboardToolArgs(
                    action="update",
                    dashboard_id=args["dashboard_id"],
                    insight_ids=args.get("insight_ids"),
                    replace_insights=args.get("replace_insights", False),
                    update_insight_ids=args.get("update_insight_ids"),
                )
            else:
                action = CreateDashboardToolArgs(
                    action="create",
                    insight_ids=args["insight_ids"],
                    name=args["name"],
                    description=args.get("description", ""),
                )

            tool = UpsertDashboardTool.__new__(UpsertDashboardTool)
            is_dangerous = tool.is_dangerous_operation(action=action)
            return {"is_dangerous": is_dangerous}

    await MaxPublicEval(
        experiment_name="upsert_dashboard_dangerous_operation",
        task=task_check_dangerous,  # type: ignore
        scores=[DangerousOperationAccuracy()],
        data=[  # type: ignore[arg-type]
            # update_insight_ids IS dangerous
            EvalCase(
                input={
                    "action": "update",
                    "dashboard_id": str(dashboard_with_insights.dashboard.id),
                    "update_insight_ids": {
                        dashboard_with_insights.insight_dau.short_id: dashboard_with_insights.insight_wau.short_id
                    },
                },
                expected={"is_dangerous": True},
            ),
            # replace_insights=True IS dangerous
            EvalCase(
                input={
                    "action": "update",
                    "dashboard_id": str(dashboard_with_insights.dashboard.id),
                    "insight_ids": [dashboard_with_insights.insight_wau.short_id],
                    "replace_insights": True,
                },
                expected={"is_dangerous": True},
            ),
            # Append mode is NOT dangerous
            EvalCase(
                input={
                    "action": "update",
                    "dashboard_id": str(dashboard_with_insights.dashboard.id),
                    "insight_ids": [dashboard_with_insights.insight_wau.short_id],
                    "replace_insights": False,
                },
                expected={"is_dangerous": False},
            ),
            # Create action is NOT dangerous
            EvalCase(
                input={
                    "action": "create",
                    "insight_ids": [dashboard_with_insights.insight_wau.short_id],
                    "name": "New Dashboard",
                    "description": "A new dashboard",
                },
                expected={"is_dangerous": False},
            ),
        ],
        pytestconfig=pytestconfig,
    )
