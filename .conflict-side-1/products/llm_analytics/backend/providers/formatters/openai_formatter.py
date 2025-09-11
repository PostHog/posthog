import json

from anthropic.types import ImageBlockParam, MessageParam, TextBlockParam, ToolResultBlockParam, ToolUseBlockParam
from openai.types.chat import (
    ChatCompletionAssistantMessageParam,
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallParam,
    ChatCompletionToolMessageParam,
    ChatCompletionUserMessageParam,
)

from products.llm_analytics.backend.providers.formatters.anthropic_typeguards import (
    is_base64_image_param,
    is_image_block_param,
    is_text_block_param,
    is_tool_result_param,
    is_tool_use_param,
    is_url_image_param,
)


def convert_to_openai_messages(anthropic_messages: list[MessageParam]) -> list[ChatCompletionMessageParam]:
    openai_messages: list[ChatCompletionMessageParam] = []

    for anthropic_message in anthropic_messages:
        if isinstance(anthropic_message["content"], str):
            message: ChatCompletionUserMessageParam | ChatCompletionAssistantMessageParam = (
                ChatCompletionUserMessageParam(role="user", content=anthropic_message["content"])
                if anthropic_message["role"] == "user"
                else ChatCompletionAssistantMessageParam(role="assistant", content=anthropic_message["content"])
            )
            openai_messages.append(message)
        else:
            if anthropic_message["role"] == "user":
                # Split content into tool results and non-tool messages
                user_non_tool_messages: list[TextBlockParam | ImageBlockParam] = []
                user_tool_messages: list[ToolResultBlockParam] = []
                for part in anthropic_message["content"]:
                    if is_tool_result_param(part):
                        user_tool_messages.append(part)
                    elif is_text_block_param(part) or is_image_block_param(part):
                        user_non_tool_messages.append(part)

                # Process tool result messages first
                for tool_message in user_tool_messages:
                    tool_content: str = ""
                    _tool_message_content = tool_message.get("content")
                    if isinstance(_tool_message_content, str):
                        tool_content = _tool_message_content
                    elif isinstance(_tool_message_content, list):
                        _content: list[str] = []
                        for part in _tool_message_content:
                            if is_image_block_param(part):
                                _content.append(f"(see following user message for image)")
                            elif is_text_block_param(part):
                                _content.append(part["text"])
                        tool_content = "\n".join(_content)

                    openai_messages.append(
                        ChatCompletionToolMessageParam(
                            {"role": "tool", "tool_call_id": tool_message["tool_use_id"], "content": tool_content}
                        )
                    )

                # Process non-tool messages
                if user_non_tool_messages:
                    non_tool_content: list[
                        ChatCompletionContentPartImageParam | ChatCompletionContentPartTextParam
                    ] = []
                    for part in user_non_tool_messages:
                        if is_image_block_param(part):
                            if is_base64_image_param(part["source"]):
                                non_tool_content.append(
                                    ChatCompletionContentPartImageParam(
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:{part['source']['media_type']};base64,{part['source']['data']}"
                                            },
                                        }
                                    )
                                )
                            elif is_url_image_param(part["source"]):
                                non_tool_content.append(
                                    ChatCompletionContentPartImageParam(
                                        {"type": "image_url", "image_url": {"url": part["source"]["url"]}}
                                    )
                                )
                        elif is_text_block_param(part):
                            non_tool_content.append(
                                ChatCompletionContentPartTextParam({"type": "text", "text": part["text"]})
                            )

                    openai_messages.append(ChatCompletionUserMessageParam(role="user", content=non_tool_content))
            elif anthropic_message["role"] == "assistant":
                assistant_non_tool_messages: list[TextBlockParam | ImageBlockParam] = []
                assistant_tool_messages: list[ToolUseBlockParam] = []

                for part in anthropic_message["content"]:
                    if is_tool_use_param(part):
                        assistant_tool_messages.append(part)
                    elif is_text_block_param(part) or is_image_block_param(part):
                        assistant_non_tool_messages.append(part)

                # Process non-tool messages
                content = None
                if assistant_non_tool_messages:
                    content = "\n".join(
                        part["text"] for part in assistant_non_tool_messages if is_text_block_param(part)
                    )

                # Process tool use messages
                tool_calls: list[ChatCompletionMessageToolCallParam] = [
                    ChatCompletionMessageToolCallParam(
                        {
                            "id": tool_message["id"],
                            "type": "function",
                            "function": {"name": tool_message["name"], "arguments": json.dumps(tool_message["input"])},
                        }
                    )
                    for tool_message in assistant_tool_messages
                ]
                if len(tool_calls) > 0:
                    openai_messages.append(
                        ChatCompletionAssistantMessageParam(role="assistant", content=content, tool_calls=tool_calls)
                    )
                else:
                    openai_messages.append(ChatCompletionAssistantMessageParam(role="assistant", content=content))

    return openai_messages
