from datetime import datetime
from typing import Any, NotRequired, TypedDict

import pytest
from unittest.mock import patch

from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score
from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    EventsNode,
    HumanMessage,
    InsightVizNode,
    TrendsQuery,
)

from posthog.models import Dashboard, DashboardTile, Insight

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation


class EvalInput(TypedDict):
    input: str
    dashboard: NotRequired[Dashboard | None]


class EvalExpected(TypedDict):
    action: str
    dashboard_name: NotRequired[str | None]
    insight_titles: NotRequired[list[str] | None]
    error: NotRequired[str | None]


DASHBOARD_OPERATION_ACCURACY_PROMPT = """
Evaluate if the agent correctly performed the dashboard operation.

<user_request>
{{input.input}}
</user_request>

<expected>
Action: {{expected.action}}
{{#expected.dashboard_name}}
Dashboard name: {{expected.dashboard_name}}
{{/expected.dashboard_name}}
Expected insight titles (by meaning): {{expected.insight_titles}}
Expected error: {{expected.error}}
</expected>

<actual_output>
Tool called: {{output.tool_called}}
Action: {{output.action}}
Tool output: {{output.tool_output}}
Error: {{output.error}}
</actual_output>

Evaluate:
1. If expected action is "No action": The agent should NOT have called upsert_dashboard. Pass if no tool was called, fail otherwise.
2. If expected action is create/update:
   a. Did the agent call the upsert_dashboard tool?
   b. Was the correct action (create/update) chosen?
   c. Does the tool output confirm a dashboard was created/updated?
   d. Do the insight titles in the tool output match the expected ones BY MEANING? Titles don't need to be exact - they should be semantically equivalent (e.g. "File activity" matches "File interactions", "User journey funnel" matches "Homepage view to signup conversion"). If expected is null/None, skip this check.
3. If error expected, was it returned?

Choose: pass (all requirements met) or fail (any requirement not met)
""".strip()


class DashboardOperationAccuracy(LLMClassifier):
    """Binary LLM judge for full agent dashboard operations (tests trajectory)."""

    def _normalize(self, output: dict | None, expected: dict | None) -> tuple[dict, dict]:
        """Ensure all keys exist with defaults to avoid Mustache errors."""
        normalized_output = {
            "tool_called": None,
            "action": None,
            "tool_output": None,
            "error": None,
            **(output or {}),
        }
        normalized_expected = {
            "action": None,
            "insight_titles": None,
            "error": None,
            "dashboard_name": None,
            **(expected or {}),
        }
        if normalized_expected["action"] is None:
            normalized_expected["action"] = "No action"
        if normalized_output["action"] is None:
            normalized_output["action"] = "No action"
        return normalized_output, normalized_expected

    async def _run_eval_async(self, output: dict | None, expected: dict | None = None, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output provided"})
        normalized_output, normalized_expected = self._normalize(output, expected)
        return await super()._run_eval_async(normalized_output, normalized_expected, **kwargs)

    def _run_eval_sync(self, output: dict | None, expected: dict | None = None, **kwargs):
        if not output:
            return Score(name=self._name(), score=0.0, metadata={"reason": "No output provided"})
        normalized_output, normalized_expected = self._normalize(output, expected)
        return super()._run_eval_sync(normalized_output, normalized_expected, **kwargs)

    def __init__(self, **kwargs):
        super().__init__(
            name="dashboard_operation_accuracy",
            prompt_template=DASHBOARD_OPERATION_ACCURACY_PROMPT,
            choice_scores={"pass": 1.0, "fail": 0.0},
            model="gpt-5.2",
            max_tokens=2048,
            reasoning_effort="medium",
            **kwargs,
        )


@pytest.fixture
def call_agent_for_dashboard(demo_org_team_user):
    """Run full agent graph with natural language dashboard requests."""
    with (
        patch(
            "ee.hogai.core.agent_modes.presets.product_analytics.has_upsert_dashboard_feature_flag", return_value=True
        ),
        patch("ee.hogai.tools.upsert_dashboard.tool.UpsertDashboardTool.is_dangerous_operation", return_value=False),
    ):
        _, team, user = demo_org_team_user

        graph = (
            AssistantGraph(team, user)
            .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
            .add_root()
            .compile(checkpointer=DjangoCheckpointer())
        )

        async def callable(input: EvalInput) -> dict:
            conversation = await Conversation.objects.acreate(team=team, user=user)
            initial_state = AssistantState(messages=[HumanMessage(content=input["input"])])
            config = RunnableConfig(configurable={"thread_id": conversation.id}, recursion_limit=48)
            raw_state = await graph.ainvoke(initial_state, config)
            state = AssistantState.model_validate(raw_state)

            return _extract_dashboard_result(state)

        yield callable


def _extract_dashboard_result(state: AssistantState) -> dict:
    """Extract dashboard operation result from final state."""
    result: dict[str, Any] = {
        "tool_called": None,
        "action": None,
        "tool_output": None,
        "error": None,
    }

    upsert_tool_call_id: str | None = None

    # Check for tool calls in messages
    for msg in state.messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.name == "upsert_dashboard":
                    result["tool_called"] = "upsert_dashboard"
                    result["action"] = tool_call.args.get("action", {}).get("action")
                    upsert_tool_call_id = tool_call.id
                    break

    # Find the tool call result message
    for msg in state.messages:
        if isinstance(msg, AssistantToolCallMessage) and msg.tool_call_id == upsert_tool_call_id:
            result["tool_output"] = msg.content
            if "error" in msg.content.lower() or "failed" in msg.content.lower():
                result["error"] = msg.content
            break

    return result


async def _create_dashboard(team, user, title: str, description: str):
    dashboard = await Dashboard.objects.acreate(team=team, name=title, description=description, created_by=user)
    insight = await Insight.objects.acreate(
        team=team,
        name="Mobile app screen views",
        query=InsightVizNode(source=TrendsQuery(series=[EventsNode(name="$pageview")])).model_dump(
            mode="json", exclude_none=True
        ),
        created_by=user,
        saved=True,
        deleted=False,
    )
    await DashboardTile.objects.acreate(dashboard=dashboard, insight=insight, layouts={}, deleted=False)
    return dashboard


@pytest.fixture(autouse=True)
async def clear_dashboards():
    start_dt = datetime.now()
    yield
    # Clean up new dashboards and insights
    async for dashboard in Dashboard.objects.filter(created_at__gte=start_dt):
        await dashboard.insights.filter(created_at__gte=start_dt).adelete()
        await dashboard.adelete()


@pytest.mark.django_db
async def eval_create_dashboard(call_agent_for_dashboard, pytestconfig):
    """Test dashboard creation via full agent with natural language prompts."""

    await MaxPublicEval(
        experiment_name="upsert_dashboard_create",
        task=call_agent_for_dashboard,
        scores=[DashboardOperationAccuracy()],
        data=[
            EvalCase(
                input=EvalInput(
                    input="I want to create a new dashboard to track user journeys from homepage to signup"
                ),
                expected=EvalExpected(
                    action="create",
                    insight_titles=["Homepage view to signup conversion", "User paths starting at homepage"],
                ),
            ),
            EvalCase(
                input=EvalInput(input="Put together a dashboard for key metrics"),
                expected=EvalExpected(
                    action="No action",
                ),
            ),
            EvalCase(
                input=EvalInput(input="Create a dashboard showing how users navigate the site"),
                expected=EvalExpected(
                    action="create",
                    # Should find this insight
                    insight_titles=["User paths starting at homepage"],
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
async def eval_update_dashboard(call_agent_for_dashboard, demo_org_team_user, pytestconfig):
    """Test dashboard updates via full agent with natural language prompts."""
    _, team, user = demo_org_team_user

    data = [
        EvalCase(
            input=EvalInput(
                input="Add conversion from sign up to file upload to my mobile app dashboard",
                dashboard=await _create_dashboard(
                    team, user, "Mobile App Metrics", "A dashboard for mobile app metrics"
                ),
            ),
            expected=EvalExpected(
                action="update",
                insight_titles=["Mobile app screen views", "Conversion from sign up to file upload"],
            ),
        ),
        EvalCase(
            input=EvalInput(
                input="The desktop app metrics dashboard needs a better name, something like '[Desktop]: Key Metrics'",
                dashboard=await _create_dashboard(
                    team, user, "Desktop App Metrics", "A dashboard for desktop app metrics"
                ),
            ),
            expected=EvalExpected(
                action="update",
                dashboard_name="[Desktop]: Key Metrics",
            ),
        ),
        EvalCase(
            input=EvalInput(
                input="Break down insights by country in the promo campaign metrics dashboard",
                dashboard=await _create_dashboard(
                    team, user, "Promo campaign metrics", "A dashboard for promo campaign metrics"
                ),
            ),
            expected=EvalExpected(
                action="update",
                insight_titles=["Mobile app screen views by country"],
            ),
        ),
    ]

    await MaxPublicEval(
        experiment_name="upsert_dashboard_update",
        task=call_agent_for_dashboard,
        scores=[DashboardOperationAccuracy()],
        data=data,
        pytestconfig=pytestconfig,
    )
