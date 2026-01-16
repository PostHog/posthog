from typing import Any

import pytest
from unittest.mock import patch

from autoevals.partial import ScorerWithPartial
from braintrust import EvalCase, Score

from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.tools.upsert_dashboard import UpsertDashboardTool
from ee.hogai.tools.upsert_dashboard.tool import CreateDashboardToolArgs, UpdateDashboardToolArgs, UpsertDashboardAction


class DangerousOperationAccuracy(ScorerWithPartial):
    """Scorer for dangerous operation detection accuracy."""

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs):
        if expected is None or output is None:
            return Score(name=self._name(), score=0.0)

        if expected.get("is_dangerous") == output.get("is_dangerous"):
            return Score(name=self._name(), score=1.0)
        return Score(name=self._name(), score=0.0)


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
