from __future__ import annotations

from typing import Optional

import pytest

from langchain_core.messages import AIMessage as LangchainAIMessage

from posthog.schema import AssistantMessage, AssistantToolCall, HumanMessage

from ee.hogai.chat_agent import AssistantGraph
from ee.hogai.django_checkpoint.checkpointer import DjangoCheckpointer
from ee.hogai.utils.types import AssistantNodeName, AssistantState
from ee.models.assistant import Conversation

from ..judge import ChoiceJudgeScorer
from ..types import EvalCase, EvalSuite


def _extract_first_tool_call(message: AssistantMessage | None) -> AssistantToolCall | None:
    if not message or not message.tool_calls:
        return None
    return message.tool_calls[0]


MEMORY_CONTENT_SCORER = ChoiceJudgeScorer(
    metric_name="memory_content_relevance",
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
- irrelevant: Completely off-topic or inappropriate content
""",
    choice_scores={
        "perfect": 1.0,
        "good": 0.7,
        "partial": 0.4,
        "irrelevant": 0.0,
    },
    prepare_output=_extract_first_tool_call,
    score_if_both_missing=1.0,
    score_if_one_missing=0.0,
)

MEMORY_CASES = [
    EvalCase(
        id="memory-1",
        name="append arr fact",
        input="calculate ARR: use the paid_bill event and the amount property.",
        expected=AssistantToolCall(
            id="1",
            name="core_memory_append",
            args={
                "memory_content": "The product uses the event paid_bill and the property amount to calculate Annual Recurring Revenue (ARR)."
            },
        ),
    ),
    EvalCase(
        id="memory-2",
        name="replace sponsorship fact",
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
    EvalCase(
        id="memory-3",
        name="omit irrelevant personal info",
        input="My name is John Doherty.",
        expected=None,
    ),
]


@pytest.fixture
def call_memory_collector(demo_org_team_user, core_memory):
    graph = (
        AssistantGraph(demo_org_team_user[1], demo_org_team_user[2])
        .add_edge(AssistantNodeName.START, AssistantNodeName.MEMORY_COLLECTOR)
        .add_memory_collector(AssistantNodeName.END, AssistantNodeName.END)
        .compile(checkpointer=DjangoCheckpointer())
    )

    async def callable(message: str) -> Optional[AssistantMessage]:
        conversation = await Conversation.objects.acreate(team=demo_org_team_user[1], user=demo_org_team_user[2])
        raw_state = await graph.ainvoke(
            AssistantState(messages=[HumanMessage(content=message)]),
            {"configurable": {"thread_id": conversation.id}},
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


def build_memory_suite(task) -> EvalSuite:
    return EvalSuite(
        experiment_name="memory",
        task=task,
        cases=MEMORY_CASES,
        metrics=[MEMORY_CONTENT_SCORER.as_metric(result_type="numeric")],
    )
