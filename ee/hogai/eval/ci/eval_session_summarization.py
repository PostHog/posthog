from functools import partial

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

    async def callable(
        messages: str | list[AssistantMessageUnion], include_search_session_recordings_context: bool
    ) -> AssistantMessage:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=messages)] if isinstance(messages, str) else messages
        )
        # Conditionally include session replay page context
        contextual_tools = (
            {"search_session_recordings": {"current_filters": {"date_from": "-7d", "filter_test_accounts": True}}}
            if include_search_session_recordings_context
            else {}
        )
        config = {
            "configurable": {
                "thread_id": conversation.id,
                "contextual_tools": contextual_tools,
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
    """Test routing between search_session_recordings (contextual) and session_summarization (root) with context."""

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
                    # Expect the period to be guessed from current filters
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
                    args={"change": "show only recordings longer than 5 minutes"},
                ),
            ),
            # Cases where session_summarization should be used (analysis/summary)
            EvalCase(
                input="summarize sessions from yesterday",
                expected=AssistantToolCall(
                    id="5",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize sessions from yesterday",
                        "should_use_current_filters": False,  # Specific time frame differs from current filters
                    },
                ),
            ),
            EvalCase(
                input="watch sessions of the user 09081 in the last 30 days",
                expected=AssistantToolCall(
                    id="6",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "watch sessions of the user 09081 in the last 30 days",
                        "should_use_current_filters": False,  # Specific user and timeframe
                    },
                ),
            ),
            EvalCase(
                input="analyze mobile user sessions from last week",
                expected=AssistantToolCall(
                    id="7",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "analyze mobile user sessions from last week",
                        "should_use_current_filters": False,  # Specific device type and timeframe
                    },
                ),
            ),
            EvalCase(
                input="summarize sessions from the last 30 days, including test accounts",
                expected=AssistantToolCall(
                    id="8",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize sessions from the last 30 days with test accounts included",
                        "should_use_current_filters": False,  # Different time frame/conditions
                    },
                ),
            ),
            # Cases where should_use_current_filters should be true (referring to current/selected filters)
            EvalCase(
                input="summarize these sessions",
                expected=AssistantToolCall(
                    id="9",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize these sessions",
                        "should_use_current_filters": True,  # "these" refers to current filters
                    },
                ),
            ),
            EvalCase(
                input="summarize all sessions",
                expected=AssistantToolCall(
                    id="10",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize all sessions",
                        "should_use_current_filters": True,  # "all" in context of filtered view
                    },
                ),
            ),
            EvalCase(
                input="summarize sessions from the last 7 days with test accounts filtered out",
                expected=AssistantToolCall(
                    id="11",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize sessions from the last 7 days with test accounts filtered out",
                        "should_use_current_filters": True,  # Matches current filters exactly
                    },
                ),
            ),
            # Ambiguous cases
            EvalCase(
                input="show me the summary of what users did with our app in the last 7 days",
                expected=AssistantToolCall(
                    id="12",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "show me what users did with our app",
                        "should_use_current_filters": True,  # Analyzing user behavior, use current context
                    },
                ),
            ),
            EvalCase(
                input="show me sessions with users who visited checkout page",
                expected=AssistantToolCall(
                    id="13",
                    name="search_session_recordings",
                    args={"change": "show me sessions with users who visited checkout page"},
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
@patch("posthoganalytics.feature_enabled", return_value=True)
async def eval_session_summarization_no_context(patch_feature_enabled, call_root_for_replay_sessions, pytestconfig):
    """Test session summarization without search_session_recordings context - should_use_current_filters should always be false."""

    # Use partial to avoid adding session search context
    task_without_context = partial(call_root_for_replay_sessions, include_search_session_recordings_context=False)

    await MaxPublicEval(
        experiment_name="session_summarization_no_context",
        task=task_without_context,
        scores=[ToolRelevance(semantic_similarity_args={"session_summarization_query"})],
        data=[
            # All cases should have should_use_current_filters=false when no context
            EvalCase(
                input="summarize sessions from yesterday",
                expected=AssistantToolCall(
                    id="1",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize sessions from yesterday",
                        "should_use_current_filters": False,  # No context, always false
                    },
                ),
            ),
            EvalCase(
                input="analyze the current recordings from today",
                expected=AssistantToolCall(
                    id="3",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "analyze the current recordings from today",
                        "should_use_current_filters": False,  # Even with "current", no context means false
                    },
                ),
            ),
            EvalCase(
                input="watch all my session recordings",
                expected=AssistantToolCall(
                    id="5",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "watch all session recordings",
                        "should_use_current_filters": False,  # Even with "all", no context means false
                    },
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )
