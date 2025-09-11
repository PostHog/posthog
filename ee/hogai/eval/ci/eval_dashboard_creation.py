import pytest

from braintrust import EvalCase

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval
from ..scorers import ToolRelevance


@pytest.fixture
def call_root_for_dashboard_creation(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "create_dashboard": AssistantNodeName.END,
                "insights": AssistantNodeName.END,
                "search_documentation": AssistantNodeName.END,
                "session_summarization": AssistantNodeName.END,
                "insights_search": AssistantNodeName.END,
                "create_and_query_insight": AssistantNodeName.END,
                "root": AssistantNodeName.END,
                "end": AssistantNodeName.END,
            }
        )
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(messages: str | list[AssistantMessageUnion]) -> AssistantMessage:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=messages)] if isinstance(messages, str) else messages
        )

        config = {
            "configurable": {
                "thread_id": conversation.id,
            }
        }
        raw_state = await graph.ainvoke(initial_state, config)
        state = AssistantState.model_validate(raw_state)
        for message in reversed(state.messages):
            if isinstance(message, AssistantMessage):
                return message
        raise AssertionError(
            f"No AssistantMessage found in state. Last message was: {state.messages[-1] if state.messages else 'no messages'}"
        )

    return callable


@pytest.mark.django_db
async def eval_tool_routing_dashboard_creation(call_root_for_dashboard_creation, pytestconfig):
    async def task_with_context(messages):
        return await call_root_for_dashboard_creation(messages)

    await MaxPublicEval(
        experiment_name="tool_routing_dashboard_creation",
        task=task_with_context,
        scores=[ToolRelevance(semantic_similarity_args={"search_insights_queries", "create_dashboard_query"})],
        data=[
            # Cases where create_dashboard should be used
            EvalCase(
                input="create a dashboard showing user engagement metrics with signup funnel and retention data",
                expected=AssistantToolCall(
                    id="1",
                    name="create_dashboard",
                    args={
                        "create_dashboard_query": "Create a dashboard showing user engagement metrics with signup funnel and retention data for Hedgebox.",
                        "search_insights_queries": [
                            {
                                "description": "Track key user engagement metrics for Hedgebox, such as daily active users, weekly active users, and event activity (e.g., file uploads, shares, and collaboration actions).",
                                "name": "User engagement metrics",
                            },
                            {
                                "description": "Visualize the signup funnel for Hedgebox, showing the steps users take from landing on the signup page to completing account creation.",
                                "name": "Signup funnel",
                            },
                            {
                                "description": "Display user retention data for Hedgebox, showing how many users return after signup over various time periods (e.g., day 1, day 7, day 30).",
                                "name": "Retention data",
                            },
                        ],
                    },
                ),
            ),
            EvalCase(
                input="create a dashboard with an insight that shows how many users were created yesterday",
                expected=AssistantToolCall(
                    id="2",
                    name="create_dashboard",
                    args={
                        "create_dashboard_query": "Create a dashboard with an insight showing how many users were created yesterday.",
                        "search_insights_queries": [
                            {
                                "description": "Shows the total number of users who were created yesterday. Filters for user creation events with a date range set to yesterday.",
                                "name": "Users created yesterday",
                            }
                        ],
                    },
                ),
            ),
            EvalCase(
                input="I want two insights one to show users in California for the past 7 days that performed 'chat with ai' events and another one that shows the trend of signups over the last 30 days. Create a dashboard with these two insights.",
                expected=AssistantToolCall(
                    id="3",
                    name="create_dashboard",
                    args={
                        "create_dashboard_query": "Create a dashboard with two insights: one showing users in California who performed 'chat with ai' events in the past 7 days, and another showing the trend of signups over the last 30 days.",
                        "search_insights_queries": [
                            {
                                "description": "List of users located in California who performed the 'chat with ai' event in the past 7 days. Filter by location (California) and event name ('chat with ai').",
                                "name": "California users who performed 'chat with ai' in last 7 days",
                            },
                            {
                                "description": "Trend of user signups over the last 30 days. Show daily counts of signup events for the past 30 days.",
                                "name": "Signup trend over last 30 days",
                            },
                        ],
                    },
                ),
            ),
            EvalCase(
                input="Find an insight that shows the trend of signups over the last 30 days and put it in a dashboard.",
                expected=AssistantToolCall(
                    id="4",
                    name="create_dashboard",
                    args={
                        "create_dashboard_query": "Create a dashboard with an insight showing the trend of signups over the last 30 days.",
                        "search_insights_queries": [
                            {
                                "description": "Shows the daily trend of user signups over the past 30 days. This insight tracks the number of signups per day to help monitor growth and user acquisition patterns.",
                                "name": "Signups trend - last 30 days",
                            }
                        ],
                    },
                ),
            ),
            # Cases where search_insights should be used
            EvalCase(
                input="I want to search for two insights one to show users in California for the past 7 days that performed 'chat with ai' events and another one that shows the trend of signups over the last 30 days.",
                expected=AssistantToolCall(
                    id="4",
                    name="create_and_query_insight",
                    args={
                        "query_description": "List users located in California who performed the 'chat with ai' event in the past 7 days."
                    },
                ),
            ),
            EvalCase(
                input="Find an insight that shows the trend of signups over the last 30 days.",
                expected=AssistantToolCall(
                    id="4",
                    name="create_and_query_insight",
                    args={
                        "query_description": "Show the daily trend of user signups over the last 30 days. Use the event that tracks new user registrations. Display the count of signups per day."
                    },
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )
