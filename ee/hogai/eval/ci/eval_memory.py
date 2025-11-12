from typing import Optional

import pytest

from autoevals.llm import LLMClassifier
from braintrust import EvalCase, Score
from langchain_core.messages import AIMessage as LangchainAIMessage

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.graph.graph import AssistantGraph
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..base import MaxPublicEval
from ..scorers import ToolRelevance


class MemoryContentRelevance(LLMClassifier):
    """Evaluate memory content relevance and formatting."""

    def __init__(self, **kwargs):
        super().__init__(
            name="memory_content_relevance",
            prompt_template="""Evaluate if the memory content is relevant and well-formatted.

Context:
- Memory content should contain factual information about the product or company
- When users explicitly request to save information (e.g., "remember that...", "remember this..."), the information should be saved even if it's not product-related (e.g., personal preferences, user context)
- Personal information or irrelevant details should be omitted UNLESS explicitly requested
- Facts should be stated clearly and consistently
- When replacing facts, the new fact should be logically related to the original

Input: {{input}}
Memory content: {{output}}
Expected content: {{expected}}

How would you rate the memory content? Choose one:
- perfect: Exactly what we want - relevant, well-formatted, and complete
- good: Relevant but could be better formatted or more complete
- partial: Some relevant content but missing key details or poorly formatted
- irrelevant: Completely off-topic or inappropriate content""",
            choice_scores={
                "perfect": 1.0,
                "good": 0.7,
                "partial": 0.4,
                "irrelevant": 0.0,
            },
            model="gpt-4.1",
            **kwargs,
        )

    async def _run_eval_async(self, output, expected, **kwargs):
        output = output.tool_calls[0] if output and output.tool_calls else None
        if output is None and expected is None:
            return Score(name=self._name(), score=1.0)
        if output is None or expected is None:
            return Score(name=self._name(), score=0.0)
        return await super()._run_eval_async(output, expected, **kwargs)

    def _run_eval_sync(self, output, expected, **kwargs):
        output = output.tool_calls[0] if output and output.tool_calls else None
        if output is None and expected is None:
            return Score(name=self._name(), score=1.0)
        if output is None or expected is None:
            return Score(name=self._name(), score=0.0)
        return super()._run_eval_sync(output, expected, **kwargs)


@pytest.fixture
def call_node(demo_org_team_user, core_memory):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_memory_collector(AssistantNodeName.END, AssistantNodeName.END)
        # TRICKY: We need to set a checkpointer here because async tests create a new event loop.
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(message: str) -> Optional[AssistantMessage]:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        raw_state = await graph.ainvoke(
            AssistantState(messages=[HumanMessage(content=message)]), {"configurable": {"thread_id": conversation.id}}
        )
        state = AssistantState.model_validate(raw_state)
        if not state.memory_collection_messages:
            return None
        last_message = state.memory_collection_messages[-1]
        if not isinstance(last_message, LangchainAIMessage):
            return None
        return AssistantMessage(
            content=last_message.content,
            tool_calls=last_message.tool_calls,
        )

    return callable


@pytest.mark.django_db
async def eval_memory(call_node, pytestconfig):
    await MaxPublicEval(
        experiment_name="memory",
        task=call_node,
        scores=[ToolRelevance(semantic_similarity_args={"memory_content", "new_fragment"}), MemoryContentRelevance()],
        data=[
            # Test saving relevant facts
            EvalCase(
                input="calculate ARR: use the paid_bill event and the amount property.",
                expected=AssistantToolCall(
                    id="1",
                    name="core_memory_append",
                    args={
                        "memory_content": "The product uses the event paid_bill and the property amount to calculate Annual Recurring Revenue (ARR)."
                    },
                ),
            ),
            # Test saving company information
            EvalCase(
                input="Our secondary target audience is technical founders or highly-technical product managers.",
                expected=AssistantToolCall(
                    id="2",
                    name="core_memory_append",
                    args={
                        "memory_content": "The company's secondary target audience is technical founders or highly-technical product managers."
                    },
                ),
            ),
            # Test fact replacement
            EvalCase(
                input="Hedgebox doesn't sponsor the YouTube channel Marius Tech Tips anymore.",
                expected=AssistantToolCall(
                    id="3",
                    name="core_memory_replace",
                    args={
                        "original_fragment": "Hedgebox sponsors the YouTube channel Marius Tech Tips.",
                        "new_fragment": "Hedgebox no longer sponsors the YouTube channel Marius Tech Tips.",
                    },
                ),
            ),
            # Test fact deletion
            EvalCase(
                input="Delete info that Hedgebox sponsored the YouTube channel Marius Tech Tips.",
                expected=AssistantToolCall(
                    id="4",
                    name="core_memory_replace",
                    args={
                        "original_fragment": "Hedgebox sponsors the YouTube channel Marius Tech Tips.",
                        "new_fragment": "",
                    },
                ),
            ),
            # Test explicit memory request
            EvalCase(
                input="Remember that I like to view the pageview trend broken down by a country.",
                expected=AssistantToolCall(
                    id="5",
                    name="core_memory_append",
                    args={"memory_content": "The user prefers to view pageview trends broken down by country."},
                ),
            ),
            # Test /remember slash command
            EvalCase(
                input="/remember Our main KPI is monthly active users (MAU)",
                expected=AssistantToolCall(
                    id="6",
                    name="core_memory_append",
                    args={"memory_content": "Our main KPI is monthly active users (MAU)"},
                ),
            ),
            # Test explicit non-product-related memory request
            EvalCase(
                input="Remember my favorite treat is chocolate",
                expected=AssistantToolCall(
                    id="7",
                    name="core_memory_append",
                    args={"memory_content": "The user's favorite treat is chocolate."},
                ),
            ),
            # Test /remember slash command with no arg
            EvalCase(
                input="/remember",
                expected=None,
            ),
            # Test omitting irrelevant personal info
            EvalCase(
                input="My name is John Doherty.",
                expected=None,
            ),
            # Test omitting irrelevant insight info
            EvalCase(
                input="Build a pageview trend for users with name John.",
                expected=None,
            ),
        ],
        pytestconfig=pytestconfig,
    )
