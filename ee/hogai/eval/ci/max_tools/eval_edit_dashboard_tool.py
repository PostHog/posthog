import pytest

from braintrust import EvalCase
from langchain_core.runnables import RunnableConfig

from posthog.models import Dashboard

from products.dashboards.backend.max_tools import EditCurrentDashboardTool

from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.eval.scorers import SemanticSimilarity
from ee.models.assistant import Conversation


async def eval_insights_addition(pytestconfig, demo_org_team_user):
    """Test that adding insights to dashboard executes correctly."""

    dashboard = await Dashboard.objects.acreate(
        team=demo_org_team_user[1],
        name="Test Dashboard",
        created_by=demo_org_team_user[2],
    )

    conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

    async def task_add_insights(insights_queries: list):
        tool = EditCurrentDashboardTool(
            team=demo_org_team_user[1],
            user=demo_org_team_user[2],
            config=RunnableConfig(
                configurable={
                    "thread_id": conversation.id,
                    "team": demo_org_team_user[1],
                    "user": demo_org_team_user[2],
                    "contextual_tools": {
                        "edit_current_dashboard": {"current_dashboard": {"id": dashboard.id, "name": dashboard.name}}
                    },
                }
            ),
        )

        result_message, _ = await tool._arun_impl(insights_to_add=insights_queries)

        return result_message

    await MaxPublicEval(
        experiment_name="insights_addition",
        task=task_add_insights,  # type: ignore
        scores=[SemanticSimilarity()],
        data=[
            EvalCase(
                input=[
                    {
                        "name": "Daily Active Users",
                        "description": "Shows the count of unique users who performed any event each day over the last 30 days.",
                    }
                ],
                expected="""**Dashboard Edited**

The dashboard [Test Dashboard](/project/17/dashboard/176) was edited successfully.
The dashboard now has 1 insight added to it.""",
            ),
            EvalCase(
                input=[
                    {
                        "name": "Signup Conversion Funnel",
                        "description": "Funnel analysis showing the conversion rate from landing page visit to completed signup.",
                    },
                    {
                        "name": "User Retention Cohorts",
                        "description": "Retention cohort analysis showing what percentage of users return after their first session.",
                    },
                ],
                expected="""**Dashboard Edited**

The dashboard [Test Dashboard](/project/17/dashboard/176) was edited successfully.
The dashboard now has 2 insights added to it.""",
            ),
            EvalCase(
                input=[
                    {
                        "name": "Revenue by Category",
                        "description": "Total revenue broken down by product category for comparison.",
                    },
                    {
                        "name": "Feature Adoption",
                        "description": "Percentage of users who have used each major product feature.",
                    },
                    {
                        "name": "Geographic Distribution",
                        "description": "Map showing where users are located globally.",
                    },
                ],
                expected="""**Dashboard Edited**

The dashboard [Test Dashboard](/project/17/dashboard/176) was edited successfully.
The dashboard now has 3 insights added to it.""",
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_combined_rename_and_add(pytestconfig, demo_org_team_user):
    """Test combined operations: renaming dashboard and adding insights simultaneously."""

    dashboard = await Dashboard.objects.acreate(
        team=demo_org_team_user[1],
        name="Original Name",
        created_by=demo_org_team_user[2],
    )

    conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

    async def task_combined_edit(args: dict):
        tool = EditCurrentDashboardTool(
            team=demo_org_team_user[1],
            user=demo_org_team_user[2],
            config=RunnableConfig(
                configurable={
                    "thread_id": conversation.id,
                    "team": demo_org_team_user[1],
                    "user": demo_org_team_user[2],
                    "contextual_tools": {
                        "edit_current_dashboard": {"current_dashboard": {"id": dashboard.id, "name": dashboard.name}}
                    },
                }
            ),
        )

        insights_to_add = None
        if "insights_to_add" in args:
            insights_to_add = args["insights_to_add"]

        result_message, _ = await tool._arun_impl(
            dashboard_name=args.get("dashboard_name"), insights_to_add=insights_to_add
        )

        await dashboard.arefresh_from_db()
        return {"message": result_message, "actual_name": dashboard.name}

    await MaxPublicEval(
        experiment_name="combined_rename_and_add",
        task=task_combined_edit,  # type: ignore
        scores=[SemanticSimilarity()],
        data=[
            EvalCase(
                input={
                    "dashboard_name": "Growth Analytics",
                    "insights_to_add": [
                        {
                            "name": "Signup Growth",
                            "description": "Daily trend of new user signups over the past 90 days.",
                        }
                    ],
                },
                expected={
                    "message": """
                    Dashboard was renamed to Growth Analytics successfully.
                    **Dashboard Edited**

  The dashboard [Growth Analytics](/project/17/dashboard/178) was edited successfully.
  The dashboard now has 1 insight added to it.""",
                    "actual_name": "Growth Analytics",
                },
            )
        ],
        pytestconfig=pytestconfig,
    )
