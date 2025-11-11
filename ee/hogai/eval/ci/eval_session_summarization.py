import pytest
from unittest.mock import MagicMock, patch

from braintrust import EvalCase
from langchain_core.runnables import RunnableConfig

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.graph.session_summaries.nodes import _SessionSearch
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState
from ee.hogai.utils.yaml import load_yaml_from_raw_llm_content
from ee.models.assistant import Conversation

from ..base import MaxPublicEval
from ..scorers import ExactMatch, SemanticSimilarity, ToolRelevance


@pytest.fixture
def call_root_for_replay_sessions(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(lambda state: AssistantNodeName.END)
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

    async def task_with_context(messages):
        return await call_root_for_replay_sessions(messages, include_search_session_recordings_context=True)

    await MaxPublicEval(
        experiment_name="tool_routing_session_replay",
        task=task_with_context,
        scores=[ToolRelevance(semantic_similarity_args={"change", "session_summarization_query", "summary_title"})],
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
                        "summary_title": "Sessions from yesterday",
                        "session_summarization_limit": -1,
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
                        "summary_title": "User 09081 sessions (last 30 days)",
                        "session_summarization_limit": -1,
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
                        "summary_title": "Mobile user sessions (last week)",
                        "session_summarization_limit": -1,
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
                        "summary_title": "All sessions with test accounts (last 30 days)",
                        "session_summarization_limit": -1,
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
                        "summary_title": "All sessions (last 7 days)",
                        "session_summarization_limit": -1,
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
                        "summary_title": "All sessions (last 7 days)",
                        "session_summarization_limit": -1,
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
                        "summary_title": "All sessions, no test accounts (last 7 days)",
                        "session_summarization_limit": -1,
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
                        "summary_title": "All sessions (last 7 days)",
                        "session_summarization_limit": -1,
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

    async def task_without_context(messages):
        return await call_root_for_replay_sessions(messages, include_search_session_recordings_context=False)

    await MaxPublicEval(
        experiment_name="session_summarization_no_context",
        task=task_without_context,
        scores=[ToolRelevance(semantic_similarity_args={"session_summarization_query", "summary_title"})],
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
                        "summary_title": "Sessions from yesterday",
                        "session_summarization_limit": -1,
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
                        "summary_title": "Sessions from today",
                        "session_summarization_limit": -1,
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
                        "summary_title": "All session recordings",
                        "session_summarization_limit": -1,
                    },
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.mark.django_db
@patch("posthoganalytics.feature_enabled", return_value=True)
async def eval_session_summarization_limit(patch_feature_enabled, call_root_for_replay_sessions, pytestconfig):
    """Test that session_summarization_limit is correctly extracted from user queries."""

    async def task_with_context(messages):
        return await call_root_for_replay_sessions(messages, include_search_session_recordings_context=True)

    async def task_without_context(messages):
        return await call_root_for_replay_sessions(messages, include_search_session_recordings_context=False)

    # Current Replay filters are in the context
    await MaxPublicEval(
        experiment_name="session_summarization_limit_with_context",
        task=task_with_context,
        scores=[ToolRelevance(semantic_similarity_args={"session_summarization_query", "summary_title"})],
        data=[
            # Explicit numeric limits with different phrasing
            EvalCase(
                input="summarize 50 sessions",
                expected=AssistantToolCall(
                    id="1",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize 50 sessions",
                        "should_use_current_filters": True,  # Assuming 50 sessions from the applied filters
                        "summary_title": "Last 50 sessions",
                        "session_summarization_limit": 50,
                    },
                ),
            ),
            EvalCase(
                input="watch the first 10 sessions from yesterday",
                expected=AssistantToolCall(
                    id="2",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "watch the first 10 sessions from yesterday",
                        "should_use_current_filters": False,  # Ask for specific timeframe
                        "summary_title": "First 10 sessions from yesterday",
                        "session_summarization_limit": 10,
                    },
                ),
            ),
            EvalCase(
                input="analyze top 200 sessions",
                expected=AssistantToolCall(
                    id="3",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "analyze top 200 sessions",
                        "should_use_current_filters": True,  # No specific timeframe, uses current filters
                        "summary_title": "Top 200 sessions",
                        "session_summarization_limit": 200,
                    },
                ),
            ),
            # Edge cases where numbers appear but are NOT limits
            EvalCase(
                input="summarize sessions with at least 10 events",
                expected=AssistantToolCall(
                    id="6",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize sessions with at least 10 events",
                        "should_use_current_filters": False,  # New explicit filter condition
                        "summary_title": "Sessions with at least 10 events",
                        "session_summarization_limit": -1,  # This is a filter condition, not a limit
                    },
                ),
            ),
            EvalCase(
                input="watch sessions longer than 5 minutes from Chrome users",
                expected=AssistantToolCall(
                    id="7",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "watch sessions longer than 5 minutes from Chrome users",
                        "should_use_current_filters": False,  # Explicit requirement for Chrome users and duration
                        "summary_title": "Sessions longer than 5 minutes from Chrome users",
                        "session_summarization_limit": -1,  # Duration is a filter, not a count limit
                    },
                ),
            ),
            # Using "first X of these" with current context
            EvalCase(
                input="summarize first 15 of these sessions",
                expected=AssistantToolCall(
                    id="9",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize first 15 of these sessions",
                        "should_use_current_filters": True,  # "these" refers to current filters
                        "summary_title": "First 15 sessions",
                        "session_summarization_limit": 15,
                    },
                ),
            ),
            # Superlative phrasing
            EvalCase(
                input="watch the 20 longest sessions from yesterday",
                expected=AssistantToolCall(
                    id="10",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "watch the 20 longest sessions from yesterday",
                        "should_use_current_filters": False,  # Ask for specific timeframe and condition
                        "summary_title": "20 longest sessions from yesterday",
                        "session_summarization_limit": 20,
                    },
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )

    # No Replay filters in the context
    await MaxPublicEval(
        experiment_name="session_summarization_limit_without_context",
        task=task_without_context,
        scores=[ToolRelevance(semantic_similarity_args={"session_summarization_query", "summary_title"})],
        data=[
            EvalCase(
                input="summarize last 100 sessions",
                expected=AssistantToolCall(
                    id="1",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "summarize last 100 sessions",
                        "should_use_current_filters": False,
                        "summary_title": "Last 100 sessions",
                        "session_summarization_limit": 100,
                    },
                ),
            ),
            EvalCase(
                input="analyze 3 sessions from each country",
                expected=AssistantToolCall(
                    id="2",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "analyze 3 sessions from each country",
                        "should_use_current_filters": False,
                        "summary_title": "3 sessions from each country",
                        "session_summarization_limit": 3,
                    },
                ),
            ),
            EvalCase(
                input="watch first 7 recordings with checkout events",
                expected=AssistantToolCall(
                    id="3",
                    name="session_summarization",
                    args={
                        "session_summarization_query": "watch first 7 recordings with checkout events",
                        "should_use_current_filters": False,
                        "summary_title": "First 7 recordings with checkout events",
                        "session_summarization_limit": 7,
                    },
                ),
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.fixture
def filter_query_tester(demo_org_team_user):
    """Simple fixture to test filter query generation."""

    async def test(input_query: str) -> str:
        # Minimal mock setup
        mock_node = MagicMock()
        mock_node._team = demo_org_team_user[1]
        mock_node._user = demo_org_team_user[2]
        search = _SessionSearch(mock_node)
        return await search._generate_filter_query(input_query, RunnableConfig())

    return test


async def eval_filter_query_generation(filter_query_tester, pytestconfig):
    """Test that filter query generation preserves search intent while removing fluff."""

    await MaxPublicEval(
        experiment_name="filter_query_generation",
        task=filter_query_tester,
        scores=[SemanticSimilarity()],
        data=[
            EvalCase(input="summarize sessions from yesterday", expected="sessions from yesterday"),
            EvalCase(input="analyze mobile user sessions from last week", expected="mobile user sessions last week"),
            EvalCase(
                input="watch last 100 sessions, I want to understand what users did in checkout flow",
                expected="last 100 sessions",
            ),
            EvalCase(
                input="hey Max,show me sessions longer than 5 minutes from Chrome users",
                expected="sessions longer than 5 minutes fromChrome users",
            ),
            EvalCase(
                input="watch recordings of user ID 12345 from past week, I want to see the UX issues they are facing",
                expected="recordings of user ID 12345 from past week",
            ),
            EvalCase(
                input="summarize iOS sessions from California with purchase events over $100, do we have a lot of these?",
                expected="iOS sessions from California with purchase events over $100",
            ),
            EvalCase(
                input="Max, I need you to watch replays of German desktop Linux users from 21.03.2024 till 24.03.2024, and tell me what problems did they encounter",
                expected="replays of German desktop Linux users from 21.03.2024 till 24.03.2024",
            ),
        ],
        pytestconfig=pytestconfig,
    )


@pytest.fixture
def yaml_fix_tester():
    """Test that load_yaml_from_raw_llm_content fixes malformed YAML."""

    def test(malformed_yaml: str) -> dict | list:
        return load_yaml_from_raw_llm_content(malformed_yaml, final_validation=True)

    return test


async def eval_yaml_fixing(yaml_fix_tester, pytestconfig):
    """Test that load_yaml_from_raw_llm_content can fix slightly malformed YAML."""

    await MaxPublicEval(
        experiment_name="yaml_fixing",
        task=yaml_fix_tester,
        scores=[ExactMatch()],
        data=[
            # Missing closing quote
            EvalCase(
                input='key: "value with missing quote',
                expected={"key": "value with missing quote"},
            ),
            # Mixed symbols in list items with malformed quotes
            EvalCase(
                input="""
- item: 'value's with apostrophe'
  description: "unclosed quote here
- item: "double quoted "value" inside"
  description: "some text with ```backticks around it```, maybe code"
""",
                expected=[
                    {"description": "unclosed quote here", "item": "value's with apostrophe"},
                    {
                        "description": "some text with ```backticks around it```, maybe code",
                        "item": 'double quoted "value" inside',
                    },
                ],
            ),
            # Mixed indentation (tabs and spaces)
            EvalCase(
                input="parent:\n\tchild: value",
                expected={"parent": {"child": "value"}},
            ),
            # Unquoted string with special chars that should be quoted
            EvalCase(
                input="url: http://example.com?param=value&other=test",
                expected={"url": "http://example.com?param=value&other=test"},
            ),
            # Missing dash for list item
            EvalCase(
                input="- item1\nitem2",
                expected=["item1", "item2"],
            ),
            # Inconsistent list/dict mixing
            EvalCase(
                input="- key: value\nother: data",
                expected={"key": "value", "other": "data"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
