from collections.abc import Sequence
from typing import Optional, TypeVar, Union

from jsonref import replace_refs
from langchain_core.messages import (
    HumanMessage as LangchainHumanMessage,
    merge_message_runs,
)

from ee.hogai.utils.types import AssistantMessageUnion
from posthog.schema import (
    AssistantMessage,
    AssistantToolCallMessage,
    HumanMessage,
    MaxUIContext,
    VisualizationMessage,
)


def remove_line_breaks(line: str) -> str:
    return line.replace("\n", " ")


def filter_and_merge_messages(
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


def find_start_message(messages: Sequence[AssistantMessageUnion], start_id: str | None = None) -> HumanMessage | None:
    for msg in messages:
        if isinstance(msg, HumanMessage) and msg.id == start_id:
            return msg
    return None


def should_output_assistant_message(candidate_message: AssistantMessageUnion) -> bool:
    """
    This is used to filter out messages that are not useful for the user.
    Filter out tool calls without a UI payload and empty assistant messages.
    """
    if isinstance(candidate_message, AssistantToolCallMessage) and candidate_message.ui_payload is None:
        return False

    if isinstance(candidate_message, AssistantMessage) and not candidate_message.content:
        return False

    return True


def find_last_ui_context(messages: Sequence[AssistantMessageUnion]) -> MaxUIContext | None:
    """Returns the last recorded UI context from all messages."""
    for message in reversed(messages):
        if isinstance(message, HumanMessage) and message.ui_context is not None:
            return message.ui_context
    return None
