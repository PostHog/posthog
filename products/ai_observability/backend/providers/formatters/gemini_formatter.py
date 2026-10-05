import json
import base64
from typing import Any, cast

from google.genai.types import Blob, Content, ContentListUnion, FunctionCall, FunctionResponse, Part

from products.ai_observability.backend.providers.formatters.anthropic_typeguards import (
    is_base64_image_param,
    is_image_block_param,
    is_text_block_param,
    is_tool_result_param,
    is_tool_use_param,
)


def _tool_call_args(input_value: Any) -> dict[str, Any]:
    if isinstance(input_value, dict):
        return input_value
    # Callers that aggregate streamed tool calls carry the arguments as a JSON string.
    if isinstance(input_value, str):
        try:
            parsed = json.loads(input_value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _tool_response_payload(content: Any) -> dict[str, Any]:
    """Shape a tool result into the dict Gemini requires for a function response."""
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        content = "\n".join(block["text"] for block in content if is_text_block_param(block))
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
        return {"result": content}
    return {"result": "" if content is None else str(content)}


def convert_anthropic_messages_to_gemini(messages: list[dict[str, Any]]) -> ContentListUnion:
    contents: list[Content] = []  # Sticking to Content, as we don't support other formats yet
    # Gemini keys a function response by function name, but Anthropic-style tool_result
    # blocks only carry the call id, so resolve names from the earlier tool_use blocks.
    tool_name_by_call_id: dict[str, str] = {}
    for message in messages:
        parts: list[Part] = []
        if isinstance(message["content"], str):
            parts.append(Part(text=message["content"]))
        elif isinstance(message["content"], list):
            for block in message["content"]:
                if is_text_block_param(block):
                    parts.append(Part(text=block["text"]))
                elif is_image_block_param(block):
                    if not is_base64_image_param(block["source"]):
                        raise ValueError("Unsupported image source type")
                    parts.append(
                        Part(
                            inline_data=Blob(
                                data=base64.b64decode(cast(str, block["source"]["data"])),
                                mime_type=block["source"]["media_type"],
                            )
                        )
                    )
                elif is_tool_use_param(block):
                    name = str(block["name"])
                    call_id = block.get("id")
                    if isinstance(call_id, str):
                        tool_name_by_call_id[call_id] = name
                    parts.append(Part(function_call=FunctionCall(name=name, args=_tool_call_args(block.get("input")))))
                elif is_tool_result_param(block):
                    call_id = block.get("tool_use_id")
                    name = tool_name_by_call_id.get(cast(str, call_id), "") or str(call_id or "unknown")
                    parts.append(
                        Part(
                            function_response=FunctionResponse(
                                name=name, response=_tool_response_payload(block.get("content"))
                            )
                        )
                    )
                else:
                    raise ValueError(f"Unsupported content block type: {type(block)}")

        contents.append(Content(role="model" if message["role"] == "assistant" else "user", parts=parts))

    return cast(ContentListUnion, contents)
