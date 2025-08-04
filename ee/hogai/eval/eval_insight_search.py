import re

import pytest
from braintrust import EvalCase

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation
from posthog.schema import HumanMessage, AssistantToolCallMessage, VisualizationMessage

from .conftest import MaxEval
from .scorers import (
    InsightSearchOutput,
    InsightSearchRelevance,
    InsightEvaluationAccuracy,
)


def extract_insight_ids_from_text(text: str) -> list[int]:
    """Extract insight IDs from text using various regex patterns."""
    insight_id_patterns = [
        r"insight.*?ID:\s*(\d+)",  # "insight ID: 4"
        r"ID:\s*(\d+)",  # "ID: 4"
        r"insight\s*(\d+)",  # "insight 4"
        r"\(#(\d+)\)",  # "(#1)"
        r"#(\d+)",  # "#1"
        r"\[.*?\]\(/project/\d+/insights/(\d+)\)",  # "[Name](/project/123/insights/1)"
        r"/insights/(\d+)\)",  # "/insights/1)"
    ]

    insight_ids = []
    for pattern in insight_id_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            try:
                insight_ids.extend([int(match) for match in matches])
            except ValueError:
                pass

    return insight_ids


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

        # Extract evaluation data from the final state
        # For now, we'll extract what we can from the messages and state
        selected_insights = []
        evaluation_result = None

        # Look through messages for visualization messages which indicate selected insights
        for msg in state.messages:
            if isinstance(msg, VisualizationMessage):
                # Extract insight info from visualization messages
                # Look for insight references in the query or plan text
                plan_text = getattr(msg, "plan", "") or ""
                query_text = getattr(msg, "query", "") or ""

                insight_ids = extract_insight_ids_from_text(plan_text + " " + query_text)
                selected_insights.extend(insight_ids)

            elif isinstance(msg, AssistantToolCallMessage):
                # Look for evaluation results in tool call messages
                try:
                    content = msg.content
                    if "Evaluation Result" in content:
                        # The InsightSearchNode evaluation logic returns responses starting with YES/NO
                        # YES means should use existing, NO means should create new
                        explanation_text = content.replace("**Evaluation Result**: ", "")
                        should_use_existing = explanation_text.strip().upper().startswith("YES")

                        evaluation_result = {"should_use_existing": should_use_existing, "explanation": content}

                        insight_ids = extract_insight_ids_from_text(content)
                        selected_insights.extend(insight_ids)
                except Exception:
                    pass

        # Check if we went to insight creation path instead
        if state.root_tool_insight_plan and not evaluation_result:
            # This means the evaluation decided NOT to use existing insights
            evaluation_result = {
                "should_use_existing": False,
                "explanation": "Evaluation decided to create new insight (root_tool_insight_plan set)",
            }

        # Remove duplicates and maintain order
        unique_insights = list(dict.fromkeys(selected_insights))

        return {
            "selected_insights": unique_insights,
            "search_query": search_query,
            "evaluation_result": evaluation_result,
            "iteration_count": None,
            "pages_read": None,
        }

    return callable


@pytest.mark.django_db
async def eval_insight_search_relevance(call_insight_search, pytestconfig):
    """Evaluate if selected insights match the search query semantically."""
    await MaxEval(
        experiment_name="insight_search_relevance",
        task=call_insight_search,
        scores=[InsightSearchRelevance()],
        data=[
            EvalCase(
                input="sql query for active users",
                expected=[18],
            ),
            EvalCase(
                input="show me trends for pageviews",
                expected=[22],
            ),
            EvalCase(
                input="funnel analysis for signup flow",
                expected=[24],
            ),
            EvalCase(
                input="user retention metrics",
                expected=[17],
            ),
            EvalCase(
                input="dashboard metrics overview",
                expected=[22],
            ),
        ],
        pytestconfig=pytestconfig,
    )


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
                input="completely novel analysis of user engagement patterns",
                expected=True,
            ),
            EvalCase(
                input="the same user retention analysis from our previous report",
                expected=True,
            ),
        ],
        pytestconfig=pytestconfig,
    )
