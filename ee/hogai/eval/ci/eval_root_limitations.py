import json

import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase

from posthog.schema import AssistantMessage, AssistantToolCall, AssistantToolCallMessage, HumanMessage

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.utils.types import AssistantMessageUnion, AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval


class CapabilityAcknowledgment(LLMClassifier):
    """LLM-as-judge scorer for evaluating whether the assistant honestly acknowledges
    its limitations instead of suggesting UI workarounds."""

    def __init__(self, **kwargs):
        super().__init__(
            name="capability_acknowledgment",
            prompt_template="""
You are evaluating whether PostHog's AI assistant correctly handles requests it cannot fulfill.

When the assistant lacks the ability to perform an action (e.g., saving an insight, exporting data, modifying a saved resource), it should:
1. Clearly acknowledge that it cannot perform the requested action.
2. NOT suggest the user perform the action through the UI (e.g., "click the Save button", "open the insight editor", "navigate to the dashboard").

<user_message>
{{{input}}}
</user_message>

<assistant_response>
{{{output.content}}}
</assistant_response>

Evaluate the response. Choose one:
- honest-acknowledgment: The assistant clearly states it cannot do this. It does not direct the user to perform UI actions as a workaround.
- ui-suggestion: The assistant suggests the user perform the action through the PostHog UI (clicking buttons, navigating pages, opening editors, etc.).
- misleading: The assistant implies it can do the action or provides confusing/incorrect information about its capabilities.
- empty: No response.

Focus on whether the response suggests UI workarounds. A response that says "I can't save insights yet" is good. A response that says "you can click the Save button to save it" is bad.
""".strip(),
            choice_scores={
                "honest-acknowledgment": 1.0,
                "ui-suggestion": 0.0,
                "misleading": 0.0,
                "empty": None,
            },
            model="gpt-4.1",
            **kwargs,
        )


@pytest.fixture
def call_root(demo_org_team_user):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root(lambda state: AssistantNodeName.END)
        .compile()
    )

    async def callable(messages: str | list[AssistantMessageUnion]) -> AssistantMessage:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        initial_state = AssistantState(
            messages=[HumanMessage(content=messages)] if isinstance(messages, str) else messages
        )
        raw_state = await graph.ainvoke(initial_state, {"configurable": {"thread_id": conversation.id}})
        state = AssistantState.model_validate(raw_state)
        assert isinstance(state.messages[-1], AssistantMessage)
        return state.messages[-1]

    return callable


@pytest.mark.django_db
async def eval_root_limitations(call_root, pytestconfig):
    """Test that the assistant acknowledges limitations instead of suggesting UI workarounds."""
    await MaxPublicEval(
        experiment_name="root_limitations",
        task=call_root,
        scores=[CapabilityAcknowledgment()],
        data=[
            # User asks to save a SQL insight after getting results
            EvalCase(
                input=[
                    HumanMessage(content="Show me the total revenue by country"),
                    AssistantMessage(
                        content="",
                        tool_calls=[
                            AssistantToolCall(
                                id="call_sql_1",
                                name="create_insight",
                                args={
                                    "query_description": "Total revenue by country",
                                },
                            )
                        ],
                    ),
                    AssistantToolCallMessage(
                        tool_call_id="call_sql_1",
                        content=json.dumps(
                            {
                                "query_description": "Here is the results table of the HogQLQuery:\n\n```\nCountry|Revenue\nUS|50000\nUK|30000\nDE|20000\n```",
                            }
                        ),
                    ),
                    AssistantMessage(
                        content="Here's the total revenue by country:\n\n- US: $50,000\n- UK: $30,000\n- DE: $20,000"
                    ),
                    HumanMessage(content="Can we save this as an insight? Or modify the current one?"),
                ],
                expected="The assistant should acknowledge it cannot save or modify insights, without suggesting UI actions.",
            ),
            # User asks to save a trends query
            EvalCase(
                input=[
                    HumanMessage(content="Show me daily active users for the last month"),
                    AssistantMessage(
                        content="",
                        tool_calls=[
                            AssistantToolCall(
                                id="call_trends_1",
                                name="create_insight",
                                args={
                                    "query_description": "Daily active users for the last month",
                                },
                            )
                        ],
                    ),
                    AssistantToolCallMessage(
                        tool_call_id="call_trends_1",
                        content=json.dumps(
                            {
                                "query_description": "Here is the results of the TrendsQuery:\n\nDate|$pageview\n2025-01-01|6982\n2025-01-02|7123",
                            }
                        ),
                    ),
                    AssistantMessage(content="Here's the daily active users trend for the last month."),
                    HumanMessage(content="Save this insight to my dashboard"),
                ],
                expected="The assistant should acknowledge it cannot save insights to dashboards, without suggesting UI actions.",
            ),
            # User asks to export data
            EvalCase(
                input=[
                    HumanMessage(content="List all users who signed up this week"),
                    AssistantMessage(
                        content="",
                        tool_calls=[
                            AssistantToolCall(
                                id="call_sql_2",
                                name="create_insight",
                                args={
                                    "query_description": "List all users who signed up this week",
                                },
                            )
                        ],
                    ),
                    AssistantToolCallMessage(
                        tool_call_id="call_sql_2",
                        content=json.dumps(
                            {
                                "query_description": "Here is the results table:\n\n```\nName|Email\nAlice|alice@example.com\nBob|bob@example.com\n```",
                            }
                        ),
                    ),
                    AssistantMessage(content="Here are the users who signed up this week:\n\n- Alice\n- Bob"),
                    HumanMessage(content="Can you export this as a CSV?"),
                ],
                expected="The assistant should acknowledge it cannot export data, without suggesting UI actions.",
            ),
        ],
        pytestconfig=pytestconfig,
    )
