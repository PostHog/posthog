from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage

from posthog.schema import AssistantMessage, AssistantMessageMetadata, AssistantToolCall


def normalize_ai_anthropic_message(message: AIMessage) -> AssistantMessage:
    message_id = message.id or str(uuid4())
    tool_calls = [
        AssistantToolCall(id=tool_call["id"], name=tool_call["name"], args=tool_call["args"])
        for tool_call in message.tool_calls
    ]
    if isinstance(message.content, str):
        return AssistantMessage(content=message.content, id=message_id, tool_calls=tool_calls)

    turns: list[str] = []
    thinking: list[dict[str, Any]] = []

    for content in message.content:
        if isinstance(content, str):
            turns.append(content)
        if isinstance(content, dict) and "type" in content:
            if content["type"] == "text":
                turns.append(content["text"])
            if content["type"] in ("thinking", "redacted_thinking"):
                thinking.append(content)

    return AssistantMessage(
        content="\n".join(turns),
        id=message_id,
        tool_calls=tool_calls,
        meta=AssistantMessageMetadata(thinking=thinking) if thinking else None,
    )


def get_thinking_from_assistant_message(message: AssistantMessage) -> list[dict[str, Any]]:
    return message.meta.thinking if message.meta and message.meta.thinking else []


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
