from uuid import uuid4

from langchain_core.messages import AIMessage

from posthog.schema import AssistantMessage, AssistantToolCall


def normalize_ai_anthropic_message(message: AIMessage) -> AssistantMessage:
    message_id = message.id or str(uuid4())
    tool_calls = [
        AssistantToolCall(id=tool_call["id"], name=tool_call["name"], args=tool_call["args"])
        for tool_call in message.tool_calls
    ]
    if isinstance(message.content, str):
        return AssistantMessage(content=message.content, id=message_id, tool_calls=tool_calls)
    turns: list[str] = []
    for content in message.content:
        if isinstance(content, str):
            turns.append(content)
        if isinstance(content, dict) and "type" in content and content["type"] == "text":
            turns.append(content["text"])
    return AssistantMessage(
        content="\n".join(turns),
        id=message_id,
        tool_calls=tool_calls,
    )
