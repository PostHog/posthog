from collections.abc import Sequence
from typing import Optional

from langchain_core.messages import HumanMessage as LangchainHumanMessage
from langchain_core.messages import merge_message_runs
from pydantic import BaseModel

from ee.hogai.utils import AssistantMessageUnion
from posthog.schema import ExperimentalAITrendsQuery, HumanMessage, VisualizationMessage


class GenerateTrendOutputModel(BaseModel):
    reasoning_steps: Optional[list[str]] = None
    answer: Optional[ExperimentalAITrendsQuery] = None


def merge_human_messages(messages: list[LangchainHumanMessage]) -> list[LangchainHumanMessage]:
    """
    Filters out duplicated human messages and merges them into one message.
    """
    contents = set()
    filtered_messages = []
    for message in messages:
        if message.content in contents:
            continue
        contents.add(message.content)
        filtered_messages.append(message)
    return merge_message_runs(filtered_messages)


def filter_trends_conversation(
    messages: Sequence[AssistantMessageUnion],
) -> tuple[list[LangchainHumanMessage], list[VisualizationMessage]]:
    """
    Splits, filters and merges the message history to be consumable by agents.
    """
    stack: list[LangchainHumanMessage] = []
    human_messages: list[LangchainHumanMessage] = []
    visualization_messages: list[VisualizationMessage] = []

    for message in messages:
        if isinstance(message, HumanMessage):
            stack.append(LangchainHumanMessage(content=message.content))
        elif isinstance(message, VisualizationMessage) and message.answer:
            if stack:
                human_messages += merge_human_messages(stack)
                stack = []
            visualization_messages.append(message)

    if stack:
        human_messages += merge_human_messages(stack)

    return human_messages, visualization_messages
