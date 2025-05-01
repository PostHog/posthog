import json

import pytest
from braintrust import EvalCase

from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState
from ee.models.assistant import Conversation
from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage

from .conftest import MaxEval
from .scorers import ToolRelevance


@pytest.fixture
def call_node(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "insights": AssistantNodeName.END,
                "docs": AssistantNodeName.END,
                "root": AssistantNodeName.END,
                "end": AssistantNodeName.END,
            }
        )
        .compile()
    )

    def callable(messages: str | list[AssistantMessageUnion]) -> AssistantMessage:
        conversation = Conversation.objects.create(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=messages)] if isinstance(messages, str) else messages
        )
        raw_state = graph.invoke(initial_state, {"configurable": {"thread_id": conversation.id}})
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
def eval_root(call_node):
    MaxEval(
        experiment_name="root",
        data=[
            EvalCase(
                input="Create an SQL insight to calculate active users recently",
                expected=AssistantToolCall(
                    id="1",
                    name="create_and_query_insight",
                    args={"query_kind": "sql", "query_description": "Calculate the number of active users recently"},
                ),
            ),
            EvalCase(
                input="Write SQL to calculate active users recently",
                expected=AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={"query_kind": "sql", "query_description": "Calculate the number of active users recently"},
                ),
            ),
            # Should propagate the dates from the previous messages
            EvalCase(
                input=[
                    HumanMessage(content="what is the trend of pageviews ytd 2025"),
                    AssistantMessage(
                        content="",
                        tool_calls=[
                            AssistantToolCall(
                                id="call_vaTlpWMBgGyvYVIMfj1ecW8F",
                                name="create_and_query_insight",
                                args={
                                    "query_kind": "trends",
                                    "query_description": "Trend of pageviews year-to-date 2025",
                                },
                            )
                        ],
                    ),
                    AssistantToolCallMessage(
                        tool_call_id="call_vaTlpWMBgGyvYVIMfj1ecW8F",
                        content=json.dumps(
                            {
                                "query_kind": "trends",
                                "query_description": "Here is the results table of the TrendsQuery I created to answer your latest question: ``` Date|$pageview 2025-01-01|6982 2025-02-01|9953 2025-03-01|7507 2025-04-01|795 2025-05-01|3 ``` The current date and time is 2025-05-01 09:07:56 UTC, which is 2025-05-01 09:07:56 in this project's timezone (UTC). It's expected that the data point for the current period can have a drop in value, as data collection is still ongoing for it. Do not point this out.",
                            }
                        ),
                    ),
                    AssistantMessage(
                        content="Here's the trend of pageviews for the year-to-date 2025: - January: 6,982 pageviews - February: 9,953 pageviews - March: 7,507 pageviews - April: 795 pageviews - May (so far): 3 pageviews Looks like February was a busy month! If you have any more questions or need further insights, just let me know!"
                    ),
                    HumanMessage(content="list the users"),
                ],
                expected=AssistantToolCall(
                    id="2",
                    name="create_and_query_insight",
                    args={
                        "query_kind": "sql",
                        "query_description": "List all users who have completed a page view in year-to-date 2025.",
                    },
                ),
            ),
        ],
        task=call_node,
        scores=[ToolRelevance(semantic_similarity_args={"query_description"})],
    )
