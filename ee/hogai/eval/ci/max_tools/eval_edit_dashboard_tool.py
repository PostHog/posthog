import pytest
from unittest.mock import MagicMock, patch

from braintrust import EvalCase
from langchain_core.runnables import RunnableConfig

from posthog.models import Dashboard

from products.dashboards.backend.max_tools import EditCurrentDashboardTool

from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.eval.scorers import SemanticSimilarity
from ee.models.assistant import Conversation


@pytest.fixture(autouse=True)
def mock_kafka_producer():
    """Mock Kafka producer to prevent Kafka errors in tests."""
    with patch("posthog.kafka_client.client._KafkaProducer.produce") as mock_produce:
        mock_future = MagicMock()
        mock_produce.return_value = mock_future
        yield


@pytest.mark.django_db
@patch("ee.hogai.graph.base.get_stream_writer", return_value=MagicMock())
async def eval_dashboard_name_update(patch_get_stream_writer, pytestconfig, demo_org_team_user):
    """Test that dashboard name updates execute correctly."""

    async def task_rename_dashboard(new_name: str):
        dashboard = await Dashboard.objects.acreate(
            team=demo_org_team_user[1],
            name="Original Dashboard Name",
            created_by=demo_org_team_user[2],
        )
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

        tool = EditCurrentDashboardTool(team=demo_org_team_user[1], user=demo_org_team_user[2])
        tool._init_run(
            RunnableConfig(
                configurable={
                    "thread_id": conversation.id,
                    "team": demo_org_team_user[1],
                    "user": demo_org_team_user[2],
                    "contextual_tools": {
                        "edit_current_dashboard": {"current_dashboard": {"id": dashboard.id, "name": dashboard.name}}
                    },
                }
            )
        )

        result_message, _ = await tool._arun_impl(dashboard_name=new_name)

        await dashboard.arefresh_from_db()
        return {"message": result_message, "actual_name": dashboard.name}

    await MaxPublicEval(
        experiment_name="dashboard_name_update",
        task=task_rename_dashboard,
        scores=[SemanticSimilarity()],
        data=[
            EvalCase(
                input="Q4 Marketing Dashboard",
                expected={
                    "message": "Dashboard was renamed to Q4 Marketing Dashboard successfully.",
                    "actual_name": "Q4 Marketing Dashboard",
                },
            ),
            EvalCase(
                input="User Engagement Analytics 2024",
                expected={
                    "message": "Dashboard was renamed to User Engagement Analytics 2024 successfully.",
                    "actual_name": "User Engagement Analytics 2024",
                },
            ),
            EvalCase(
                input="Sales Performance Overview",
                expected={
                    "message": "Dashboard was renamed to Sales Performance Overview successfully.",
                    "actual_name": "Sales Performance Overview",
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
@patch("ee.hogai.graph.base.get_stream_writer", return_value=MagicMock())
async def eval_insights_addition(patch_get_stream_writer, pytestconfig, demo_org_team_user):
    """Test that adding insights to dashboard executes correctly."""

    dashboard = await Dashboard.objects.acreate(
        team=demo_org_team_user[1],
        name="Test Dashboard",
        created_by=demo_org_team_user[2],
    )

    conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

    async def task_add_insights(insights_queries: list):
        tool = EditCurrentDashboardTool(team=demo_org_team_user[1], user=demo_org_team_user[2])
        tool._init_run(
            RunnableConfig(
                configurable={
                    "thread_id": conversation.id,
                    "team": demo_org_team_user[1],
                    "user": demo_org_team_user[2],
                    "contextual_tools": {
                        "edit_current_dashboard": {"current_dashboard": {"id": dashboard.id, "name": dashboard.name}}
                    },
                }
            )
        )

        result_message, _ = await tool._arun_impl(insights_to_add=insights_queries)

        return result_message

    await MaxPublicEval(
        experiment_name="insights_addition",
        task=task_add_insights,
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
        tool = EditCurrentDashboardTool(team=demo_org_team_user[1], user=demo_org_team_user[2])
        tool._init_run(
            RunnableConfig(
                configurable={
                    "thread_id": conversation.id,
                    "team": demo_org_team_user[1],
                    "user": demo_org_team_user[2],
                    "contextual_tools": {
                        "edit_current_dashboard": {"current_dashboard": {"id": dashboard.id, "name": dashboard.name}}
                    },
                }
            )
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
        task=task_combined_edit,
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


@pytest.mark.django_db
async def eval_error_handling(pytestconfig, demo_org_team_user):
    """Test error handling for invalid dashboard IDs and missing context."""

    conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])

    async def task_with_errors(error_scenario: str):
        tool = EditCurrentDashboardTool(team=demo_org_team_user[1], user=demo_org_team_user[2])

        contextual_tools = {}
        if error_scenario == "missing_context":
            contextual_tools = {"edit_current_dashboard": {}}
        elif error_scenario == "missing_dashboard_id":
            contextual_tools = {"edit_current_dashboard": {"current_dashboard": {"name": "Test Dashboard"}}}
        elif error_scenario == "invalid_dashboard_id":
            contextual_tools = {
                "edit_current_dashboard": {"current_dashboard": {"id": 999999, "name": "Test Dashboard"}}
            }

        tool._init_run(
            RunnableConfig(
                configurable={
                    "thread_id": conversation.id,
                    "team": demo_org_team_user[1],
                    "user": demo_org_team_user[2],
                    "contextual_tools": contextual_tools,
                }
            )
        )

        try:
            result_message, _ = await tool._arun_impl(dashboard_name="New Name")
            return {"success": False, "message": result_message}
        except ValueError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    await MaxPublicEval(
        experiment_name="error_handling",
        task=task_with_errors,
        scores=[SemanticSimilarity()],
        data=[
            EvalCase(
                input="missing_context",
                expected={
                    "success": False,
                    "error": "Context `current_dashboard` is required for the `edit_current_dashboard` tool",
                },
            ),
            EvalCase(
                input="missing_dashboard_id",
                expected={
                    "success": False,
                    "error": "Dashboard ID not found in context",
                },
            ),
            EvalCase(
                input="invalid_dashboard_id",
                expected={
                    "success": False,
                    "message": "Dashboard was not renamed to New Name.",
                },
            ),
        ],
        pytestconfig=pytestconfig,
    )
