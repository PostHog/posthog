from collections.abc import Sequence
from typing import Optional, TypeVar, Union

from jsonref import replace_refs
from langchain_core.messages import (
    HumanMessage as LangchainHumanMessage,
    merge_message_runs,
)

from posthog.schema import (
    AssistantMessage,
    HumanMessage,
    VisualizationMessage,
)

from .types import AssistantMessageUnion


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")


def filter_messages(
    messages: Sequence[AssistantMessageUnion],
    entity_filter: Union[tuple[type[AssistantMessageUnion], ...], type[AssistantMessageUnion]] = (
        AssistantMessage,
        VisualizationMessage,
    ),
) -> list[AssistantMessageUnion]:
    """
    Filters and merges the message history to be consumable by agents. Returns human and AI messages.
    """
    stack: list[LangchainHumanMessage] = []
    filtered_messages: list[AssistantMessageUnion] = []

    def _merge_stack(stack: list[LangchainHumanMessage]) -> list[HumanMessage]:
        return [
            HumanMessage(content=langchain_message.content, id=langchain_message.id)
            for langchain_message in merge_message_runs(stack)
        ]

    for message in messages:
        if isinstance(message, HumanMessage):
            stack.append(LangchainHumanMessage(content=message.content, id=message.id))
        elif isinstance(message, entity_filter):
            if stack:
                filtered_messages += _merge_stack(stack)
                stack = []
            filtered_messages.append(message)

    if stack:
        filtered_messages += _merge_stack(stack)

    return filtered_messages


T = TypeVar("T", bound=AssistantMessageUnion)


def find_last_message_of_type(messages: Sequence[AssistantMessageUnion], message_type: type[T]) -> Optional[T]:
    return next((msg for msg in reversed(messages) if isinstance(msg, message_type)), None)


def slice_messages_to_conversation_start(
    messages: Sequence[AssistantMessageUnion], start_id: Optional[str] = None
) -> Sequence[AssistantMessageUnion]:
    result = []
    for msg in messages:
        result.append(msg)
        if msg.id == start_id:
            break
    return result


def dereference_schema(schema: dict) -> dict:
    new_schema: dict = replace_refs(schema, proxies=False, lazy_load=False)
    if "$defs" in new_schema:
        new_schema.pop("$defs")
    return new_schema
