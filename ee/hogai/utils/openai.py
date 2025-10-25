from collections.abc import Mapping, Sequence

from langchain_core import messages

from posthog.schema import AssistantMessage, AssistantToolCallMessage, ContextMessage, FailureMessage, HumanMessage

from ee.hogai.utils.types.base import AssistantMessageUnion


def convert_human_message_to_openai_message(message: HumanMessage) -> messages.HumanMessage:
    return messages.HumanMessage(content=message.content, id=message.id)


def convert_context_message_to_openai_message(message: ContextMessage) -> messages.HumanMessage:
    return messages.HumanMessage(content=message.content)


def convert_assistant_message_to_openai_message(
    message: AssistantMessage, tool_result_map: Mapping[str, AssistantToolCallMessage]
) -> list[messages.BaseMessage]:
    history: list[messages.BaseMessage] = []

    # Filter out tool calls without a tool response, so the completion doesn't fail.
    tool_calls = [tool for tool in (message.model_dump()["tool_calls"] or []) if tool["id"] in tool_result_map]

    history.append(messages.AIMessage(content=message.content, tool_calls=tool_calls, id=message.id))

    # Append associated tool call messages.
    for tool_call in tool_calls:
        tool_call_id = tool_call["id"]
        result_message = tool_result_map[tool_call_id]
        history.append(
            messages.ToolMessage(content=result_message.content, tool_call_id=tool_call_id, id=result_message.id)
        )

    return history


def convert_failure_message_to_openai_message(message: FailureMessage) -> messages.AIMessage:
    return messages.AIMessage(content=message.content or "An unknown failure occurred.", id=message.id)


def convert_to_openai_message(
    message: AssistantMessageUnion, tool_result_map: Mapping[str, AssistantToolCallMessage]
) -> list[messages.BaseMessage]:
    if isinstance(message, HumanMessage):
        return [convert_human_message_to_openai_message(message)]
    if isinstance(message, ContextMessage):
        return [convert_context_message_to_openai_message(message)]
    elif isinstance(message, AssistantMessage):
        return convert_assistant_message_to_openai_message(message, tool_result_map)
    elif isinstance(message, FailureMessage):
        return [convert_failure_message_to_openai_message(message)]
    raise ValueError(f"Unknown message type: {type(message)}")


def convert_to_openai_messages(
    conversation: Sequence[AssistantMessageUnion],
    tool_result_map: Mapping[str, AssistantToolCallMessage],
) -> list[messages.BaseMessage]:
    history: list[messages.BaseMessage] = []
    for message in conversation:
        try:
            history.extend(convert_to_openai_message(message, tool_result_map))
        except ValueError:
            continue
    return history
