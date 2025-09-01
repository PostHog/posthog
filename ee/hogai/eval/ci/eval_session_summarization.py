import pytest
from unittest.mock import patch

from braintrust import EvalCase

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph import AssistantGraph
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval
from ..scorers import ToolRelevance


@pytest.fixture
def call_root_for_replay_sessions(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(
            {
                "insights": AssistantNodeName.END,
                "search_documentation": AssistantNodeName.END,
                "session_summarization": AssistantNodeName.END,
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
        # Simulate session replay page context
        config = {
            "configurable": {
                "thread_id": conversation.id,
                "contextual_tools": {
                    "search_session_recordings": {"current_filters": {"date_from": "-7d", "filter_test_accounts": True}}
                },
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
@patch("posthoganalytics.feature_enabled", return_value=True)
async def eval_tool_routing_session_replay(patch_feature_enabled, call_root_for_replay_sessions, pytestconfig):
    """Test routing between search_session_recordings (contextual) and session_summarization (root)."""

    await MaxPublicEval(
        experiment_name="tool_routing_session_replay",
        task=call_root_for_replay_sessions,
        scores=[ToolRelevance(semantic_similarity_args={"change", "session_summarization_query"})],
        data=[
            # Cases where search_session_recordings should be used (filtering/searching)
            EvalCase(
                input="show me recordings from mobile users",
                expected=AssistantToolCall(
                    id="1",
                    name="search_session_recordings",
                    args={"change": "show me recordings from mobile users"},
                ),
            ),
            EvalCase(
                input="filter replay sessions that used chrome browser",
                expected=AssistantToolCall(
                    id="2",
                    name="search_session_recordings",
                    args={"change": "filter replay sessions that used chrome browser"},
                ),
            ),
            EvalCase(
                input="show recordings longer than 5 minutes",
                expected=AssistantToolCall(
                    id="3",
                    name="search_session_recordings",
                    args={"change": "show recordings longer than 5 minutes"},
                ),
            ),
            # Cases where session_summarization should be used (analysis/summary)
            EvalCase(
                input="summarize sessions from yesterday",
                expected=AssistantToolCall(
                    id="5",
                    name="session_summarization",
                    args={"session_summarization_query": "summarize sessions from yesterday"},
                ),
            ),
            EvalCase(
                input="watch sessions of the user 09081 in the last 7 days",
                expected=AssistantToolCall(
                    id="6",
                    name="session_summarization",
                    args={"session_summarization_query": "watch sessions of the user 09081 in the last 7 days"},
                ),
            ),
            EvalCase(
                input="analyze mobile user sessions from last week",
                expected=AssistantToolCall(
                    id="7",
                    name="session_summarization",
                    args={"session_summarization_query": "analyze mobile user sessions from last week"},
                ),
            ),
            # Edge cases - ambiguous queries
            EvalCase(
                input="show me what users did on the checkout page",
                expected=AssistantToolCall(
                    id="9",
                    name="session_summarization",
                    args={"session_summarization_query": "show me what users did on the checkout page"},
                ),
            ),
            EvalCase(
                input="replay user sessions from this morning",
                expected=AssistantToolCall(
                    id="10",
                    name="session_summarization",
                    args={"session_summarization_query": "replay user sessions from this morning"},
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )
