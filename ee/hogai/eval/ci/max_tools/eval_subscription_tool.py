"""Evaluations for subscription MCP tools.

Tests that the agent correctly identifies subscription-related user intents
and invokes the right subscription tool with appropriate parameters.

NOTE: These evals require the internal agent to have access to subscription
tools. Currently, subscriptions are MCP-only tools (not available in any
AgentMode). To run these evals, subscription tools need to be registered
in an agent mode (e.g., PRODUCT_ANALYTICS) or a dedicated SUBSCRIPTIONS
mode needs to be added.
"""

from typing import Any, TypedDict

import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score
from langchain_core.runnables import RunnableConfig

from posthog.schema import AgentMode, AssistantMessage, AssistantToolCallMessage, HumanMessage

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.eval.base import MaxPublicEval
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation


class EvalInput(TypedDict):
    input: str


SUBSCRIPTION_OPERATION_ACCURACY_PROMPT = """
Evaluate if the agent correctly performed the subscription operation.

<user_request>
{{input.input}}
</user_request>

<expected>
{{#expected}}
{{#expected.tool_called}}
Tool called: {{expected.tool_called}}
{{/expected.tool_called}}
{{#expected.has_insight}}
Should reference an insight: {{expected.has_insight}}
{{/expected.has_insight}}
{{#expected.has_dashboard}}
Should reference a dashboard: {{expected.has_dashboard}}
{{/expected.has_dashboard}}
{{#expected.frequency}}
Expected frequency: {{expected.frequency}}
{{/expected.frequency}}
{{#expected.target_type}}
Expected target type: {{expected.target_type}}
{{/expected.target_type}}
{{#expected.is_delete}}
Should soft-delete: {{expected.is_delete}}
{{/expected.is_delete}}
{{#expected.checks_slack}}
Should check for Slack integration availability: {{expected.checks_slack}}
{{/expected.checks_slack}}
{{#expected.asks_channel}}
Should ask the user whether they want email or Slack: {{expected.asks_channel}}
{{/expected.asks_channel}}
{{/expected}}

<actual_output>
Tool called: {{output.tool_called}}
Tool output: {{output.tool_output}}
Tool args (if any): {{output.tool_args}}
Error: {{output.error}}
</actual_output>

Evaluate:
1. Did the agent call the expected tool (if specified)?
2. Were the arguments appropriate for the user's request?
3. If creating, does it include the right frequency, target_type, and insight/dashboard reference?
4. If listing, did it apply relevant filters?
5. If deactivating, did it set deleted to true?
6. If Slack was requested, did the agent check for a Slack integration first (via integrations-list)?
7. If the user's intent is ambiguous about channel, did the agent ask whether they want email or Slack?

Choose: pass (all requirements met) or fail (any requirement not met)
""".strip()


class SubscriptionOperationAccuracy(LLMClassifier):
    """Binary LLM judge for subscription tool operations."""

    def _normalize(self, output: dict | None, expected: dict | None) -> tuple[dict, dict]:
        normalized_output = {
            "tool_called": None,
            "tool_output": None,
            "tool_args": None,
            "error": None,
            **(output or {}),
        }
        normalized_expected = {**(expected or {})}
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
            name="subscription_operation_accuracy",
            prompt_template=SUBSCRIPTION_OPERATION_ACCURACY_PROMPT,
            choice_scores={"pass": 1.0, "fail": 0.0},
            model="gpt-5.2",
            max_tokens=2048,
            reasoning_effort="medium",
            **kwargs,
        )


SUBSCRIPTION_TOOL_NAMES = {
    "subscriptions-list",
    "subscriptions-create",
    "subscriptions-retrieve",
    "subscriptions-partial-update",
}


def _extract_subscription_result(state: AssistantState) -> dict[str, Any]:
    """Extract subscription tool invocation from agent state."""
    result: dict[str, Any] = {
        "tool_called": None,
        "tool_output": None,
        "tool_args": None,
        "error": None,
    }

    subscription_tool_call_id: str | None = None

    for msg in state.messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.name in SUBSCRIPTION_TOOL_NAMES:
                    result["tool_called"] = tool_call.name
                    result["tool_args"] = tool_call.args
                    subscription_tool_call_id = tool_call.id
                    break

    for msg in state.messages:
        if isinstance(msg, AssistantToolCallMessage) and msg.tool_call_id == subscription_tool_call_id:
            result["tool_output"] = msg.content
            if msg.content and ("error" in msg.content.lower() or "invalid" in msg.content.lower()):
                result["error"] = msg.content
            break

    return result


@pytest.fixture
def call_agent_for_subscription(demo_org_team_user):
    """Run full agent graph with natural language subscription requests."""
    _, team, user = demo_org_team_user

    graph = (
        AssistantGraph(team, user)
        .add_edge(AssistantNodeName.START, AssistantNodeName.ROOT)
        .add_root()
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(input: EvalInput) -> dict:
        conversation = await Conversation.objects.acreate(team=team, user=user)
        initial_state = AssistantState(
            messages=[HumanMessage(content=input["input"])],
            agent_mode=AgentMode.PRODUCT_ANALYTICS,
        )
        config = RunnableConfig(configurable={"thread_id": conversation.id}, recursion_limit=48)
        raw_state = await graph.ainvoke(initial_state, config)
        state = AssistantState.model_validate(raw_state)
        return _extract_subscription_result(state)

    yield callable


@pytest.mark.django_db
async def eval_subscription_management_llm(call_agent_for_subscription, pytestconfig):
    """Test subscription management via full agent with natural language prompts."""
    await MaxPublicEval(
        experiment_name="subscription_management_llm",
        task=call_agent_for_subscription,
        scores=[SubscriptionOperationAccuracy()],
        data=[
            EvalCase(
                input=EvalInput(input="Send me a daily email update of my pageview trends insight"),
                expected={
                    "tool_called": "subscriptions-create",
                    "has_insight": True,
                    "frequency": "daily",
                    "target_type": "email",
                },
                metadata={"test_type": "create_daily_email"},
            ),
            EvalCase(
                input=EvalInput(input="What subscriptions do I have?"),
                expected={
                    "tool_called": "subscriptions-list",
                },
                metadata={"test_type": "list_subscriptions"},
            ),
            EvalCase(
                input=EvalInput(input="Subscribe me to weekly Monday updates on my revenue dashboard"),
                expected={
                    "tool_called": "subscriptions-create",
                    "has_dashboard": True,
                    "frequency": "weekly",
                    "target_type": "email",
                },
                metadata={"test_type": "create_weekly_dashboard"},
            ),
            EvalCase(
                input=EvalInput(input="Stop sending me that daily insight email, subscription 42"),
                expected={
                    "tool_called": "subscriptions-partial-update",
                    "is_delete": True,
                },
                metadata={"test_type": "deactivate_subscription"},
            ),
            EvalCase(
                input=EvalInput(input="Change my subscription to send weekly instead of daily"),
                expected={
                    "tool_called": "subscriptions-partial-update",
                    "frequency": "weekly",
                },
                metadata={"test_type": "update_frequency"},
            ),
            EvalCase(
                input=EvalInput(input="Send this insight to our #analytics Slack channel every day"),
                expected={
                    "tool_called": "integrations-list",
                    "checks_slack": True,
                },
                metadata={"test_type": "slack_channel_check_integration"},
            ),
            EvalCase(
                input=EvalInput(input="I want updates on this insight"),
                expected={
                    "asks_channel": True,
                },
                metadata={"test_type": "asks_email_or_slack"},
            ),
        ],
        pytestconfig=pytestconfig,
    )
