import re

import pytest
from braintrust import EvalCase

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage, VisualizationMessage

from .conftest import MaxEval
from .scorers import (
    InsightSearchOutput,
    InsightEvaluationAccuracy,
)


def extract_evaluation_info_from_state(state) -> dict:
    """Extract evaluation information from the final assistant state."""
    visualization_messages = [msg for msg in state.messages if isinstance(msg, VisualizationMessage)]

    evaluation_message = None
    found_insights_in_evaluation = False
    for msg in state.messages:
        if hasattr(msg, "content") and "Evaluation Result" in str(msg.content):
            evaluation_message = msg.content
            content = str(msg.content)
            if "Found" in content and "relevant insight" in content:
                found_insights_in_evaluation = True
            break

    # Determine if insights were selected or rejected
    # Use both VisualizationMessage presence AND evaluation result content
    has_selected_insights = len(visualization_messages) > 0 or found_insights_in_evaluation
    is_creating_new_insight = bool(state.root_tool_insight_plan)

    # Also check for "No existing insights found" message which indicates new insight creation
    # BUT only if we don't already have insights selected (VisualizationMessage takes precedence)
    if not is_creating_new_insight and not has_selected_insights:
        for msg in state.messages:
            if hasattr(msg, "content"):
                content = str(msg.content)
                if "No existing insights found matching your query" in content:
                    is_creating_new_insight = True
                    break

    selected_insight_ids = []
    if has_selected_insights:
        for msg in state.messages:
            if hasattr(msg, "content"):
                content = str(msg.content)
                # Look for numeric IDs first
                id_matches = re.findall(
                    r"(?:Insight\s+ID\s+|Insight\s+|Selected\s+insight\s+)(\d+)", content, re.IGNORECASE
                )
                for match in id_matches:
                    try:
                        insight_id = int(match)
                        if insight_id not in selected_insight_ids:
                            selected_insight_ids.append(insight_id)
                    except ValueError:
                        pass

                # Also look for short IDs in URLs like /insights/PHIpzaKI
                url_matches = re.findall(r"/insights/([A-Za-z0-9_-]+)", content)
                for short_id in url_matches:
                    # Convert short ID to string representation for consistency
                    if short_id not in selected_insight_ids:
                        selected_insight_ids.append(short_id)

    return {
        "selected_insights": selected_insight_ids,
        "has_selected_insights": has_selected_insights,
        "is_creating_new_insight": is_creating_new_insight,
        "evaluation_message": evaluation_message,
        "visualization_count": len(visualization_messages),
    }


@pytest.fixture
def call_insight_search(demo_org_team_user):
    """Fixture that creates a callable for executing insight search workflows."""
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "insights": AssistantNodeName.INSIGHTS_SUBGRAPH,
                "search_documentation": AssistantNodeName.END,
                "root": AssistantNodeName.END,
                "end": AssistantNodeName.END,
                "insights_search": AssistantNodeName.INSIGHTS_SEARCH,
            }
        )
        .add_insights()
        .add_insights_search()
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(search_query: str) -> InsightSearchOutput:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=f"Search for insights: {search_query}")],
            search_insights_query=search_query,
        )

        raw_state = await graph.ainvoke(initial_state, {"configurable": {"thread_id": conversation.id}})
        state = AssistantState.model_validate(raw_state)

        eval_info = extract_evaluation_info_from_state(state)

        if eval_info["is_creating_new_insight"]:
            evaluation_result = {
                "should_use_existing": False,
                "explanation": "Evaluation decided to create new insight (root_tool_insight_plan set)",
            }
        elif eval_info["has_selected_insights"]:
            evaluation_result = {
                "should_use_existing": True,
                "explanation": f"Selected {eval_info['visualization_count']} insight(s) - found visualization messages",
            }
        else:
            evaluation_result = {
                "should_use_existing": False,
                "explanation": "No insights selected and no new insight creation triggered",
            }

        selected_insights = eval_info["selected_insights"]
        if not selected_insights and eval_info["has_selected_insights"]:
            # Return empty list to make the failure visible in evaluation
            selected_insights = []

        unique_insights = list(dict.fromkeys(selected_insights))

        return {
            "selected_insights": unique_insights,
            "search_query": search_query,
            "evaluation_result": evaluation_result,
        }

    return callable


@pytest.mark.django_db
async def eval_insight_evaluation_accuracy(call_insight_search, pytestconfig):
    """Evaluate the accuracy of the insight evaluation decision."""
    await MaxEval(
        experiment_name="insight_evaluation_accuracy",
        task=call_insight_search,
        scores=[InsightEvaluationAccuracy()],
        data=[
            EvalCase(
                input="show me the exact same pageview trends we analyzed last week",
                expected=True,
            ),
            EvalCase(
                input="pageview trends but broken down by device type",
                expected=True,
            ),
            EvalCase(
                input="show me conversion rates for purple unicorn purchases by left-handed users",
                expected=False,
            ),
            EvalCase(
                input="create an insight for pokemon cards sold yesterday",
                expected=False,
            ),
        ],
        pytestconfig=pytestconfig,
    )
