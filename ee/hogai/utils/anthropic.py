from collections.abc import Mapping, Sequence
from typing import Any, cast

from langchain_core import messages
from langchain_core.messages import BaseMessage

from posthog.schema import AssistantMessage, AssistantToolCallMessage, ContextMessage, FailureMessage, HumanMessage

from ee.hogai.utils.types.base import AssistantMessageUnion


def get_anthropic_thinking_from_assistant_message(message: AssistantMessage) -> list[dict[str, Any]]:
    if message.meta and message.meta.thinking:
        return [item for item in message.meta.thinking if item["type"] in ("thinking", "redacted_thinking")]
    return []


def add_cache_control(message: BaseMessage) -> BaseMessage:
    if isinstance(message.content, str):
        message.content = [
            {"type": "text", "text": message.content, "cache_control": {"type": "ephemeral"}},
        ]
    if message.content:
        last_content = message.content[-1]
        if isinstance(last_content, str):
            message.content[-1] = {"type": "text", "text": last_content, "cache_control": {"type": "ephemeral"}}
        else:
            last_content["cache_control"] = {"type": "ephemeral"}
    return message


def convert_human_message_to_anthropic_message(message: HumanMessage) -> messages.HumanMessage:
    return messages.HumanMessage(content=[{"type": "text", "text": message.content}])


def convert_context_message_to_anthropic_message(message: ContextMessage) -> messages.HumanMessage:
    return messages.HumanMessage(content=[{"type": "text", "text": message.content}])


def convert_assistant_message_to_anthropic_message(
    message: AssistantMessage, tool_result_map: Mapping[str, AssistantToolCallMessage]
) -> list[messages.BaseMessage]:
    history: list[messages.BaseMessage] = []
    content = get_anthropic_thinking_from_assistant_message(message)
    if message.content:
        content.append({"type": "text", "text": message.content})

    # Filter out tool calls without a tool response, so the completion doesn't fail.
    tool_calls = [tool for tool in (message.model_dump()["tool_calls"] or []) if tool["id"] in tool_result_map]

    if content or tool_calls:
        history.append(
            messages.AIMessage(
                content=cast(list[str | dict[str, Any]], content),
                tool_calls=tool_calls,
            )
        )

    # Append associated tool call messages.
    for tool_call in tool_calls:
        tool_call_id = tool_call["id"]
        result_message = tool_result_map.get(tool_call_id)
        if result_message is None:
            continue
        history.append(
            messages.HumanMessage(
                content=[{"type": "tool_result", "tool_use_id": tool_call_id, "content": result_message.content}],
            ),
        )

    return history


def convert_failure_message_to_anthropic_message(message: FailureMessage) -> messages.HumanMessage:
    return messages.HumanMessage(
        content=[{"type": "text", "text": message.content or "An unknown failure occurred."}],
    )


def convert_to_anthropic_message(
    message: AssistantMessageUnion, tool_result_map: Mapping[str, AssistantToolCallMessage]
) -> list[messages.BaseMessage]:
    if isinstance(message, HumanMessage):
        return [convert_human_message_to_anthropic_message(message)]
    if isinstance(message, ContextMessage):
        return [convert_context_message_to_anthropic_message(message)]
    elif isinstance(message, AssistantMessage):
        return convert_assistant_message_to_anthropic_message(message, tool_result_map)
    elif isinstance(message, FailureMessage):
        return [convert_failure_message_to_anthropic_message(message)]
    raise ValueError(f"Unknown message type: {type(message)}")


def convert_to_anthropic_messages(
    conversation: Sequence[AssistantMessageUnion],
    tool_result_map: Mapping[str, AssistantToolCallMessage],
) -> list[messages.BaseMessage]:
    history: list[messages.BaseMessage] = []
    for message in conversation:
        try:
            history.extend(convert_to_anthropic_message(message, tool_result_map))
        except ValueError:
            continue
    return history
