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

# Gemini 3 rejects a request when the first function call in a replayed model turn has no
# thought signature. Imported Anthropic-style blocks never carry one, so use the documented
# dummy that skips validation on both the Gemini API and Vertex:
# https://ai.google.dev/gemini-api/docs/thought-signatures#faqs
_SKIP_THOUGHT_SIGNATURE = b"skip_thought_signature_validator"


class MessageConversionError(ValueError):
    """A message cannot be converted to the provider's wire format.

    The message carries the reason and is safe to show to the user. Defined here instead
    of `llm.errors` because `llm/__init__` imports the providers, which import this module,
    so the reverse import would be a cycle. The Gemini adapter maps this to
    `ProviderRequestRejectedError`.
    """


def _tool_call_args(input_value: Any, tool_name: str) -> dict[str, Any]:
    if input_value is None:
        return {}
    if isinstance(input_value, dict):
        return input_value
    # Callers that aggregate streamed tool calls carry the arguments as a JSON string.
    # Anything that does not parse to an object gets rejected rather than silently
    # replaced, which would re-run the conversation with different arguments.
    if isinstance(input_value, str):
        try:
            parsed = json.loads(input_value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    raise MessageConversionError(
        f"Tool call arguments for '{tool_name}' are not a JSON object. Fix the arguments, then run again."
    )


def _tool_response_payload(content: Any, *, is_error: bool = False) -> dict[str, Any]:
    """Shape a tool result into the dict Gemini requires for a function response.

    A result marked `is_error` goes under the `error` key, which is how Gemini
    distinguishes a failed tool run from an ordinary result.
    """
    value: Any
    if isinstance(content, list):
        # A Gemini function response is a dict, so media blocks cannot cross as-is.
        # Leave a marker rather than silently dropping them, which would turn an
        # image-only result into an empty one.
        rendered: list[str] = []
        for block in content:
            if is_text_block_param(block):
                rendered.append(block["text"])
            elif is_image_block_param(block):
                rendered.append("[image omitted]")
            else:
                rendered.append("[unsupported content omitted]")
        content = "\n".join(rendered)
    if isinstance(content, dict):
        value = content
    elif isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        value = parsed if isinstance(parsed, dict) else content
    else:
        value = "" if content is None else str(content)
    if is_error:
        return {"error": value}
    return value if isinstance(value, dict) else {"result": value}


def convert_anthropic_messages_to_gemini(messages: list[dict[str, Any]]) -> ContentListUnion:
    contents: list[Content] = []  # Sticking to Content, as we don't support other formats yet
    # Gemini keys a function response by function name, but Anthropic-style tool_result
    # blocks only carry the call id, so resolve names from the earlier tool_use blocks.
    tool_name_by_call_id: dict[str, str] = {}
    for message in messages:
        parts: list[Part] = []
        is_first_function_call = True
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
                    parts.append(
                        Part(
                            function_call=FunctionCall(
                                id=call_id if isinstance(call_id, str) else None,
                                name=name,
                                args=_tool_call_args(block.get("input"), name),
                            ),
                            thought_signature=_SKIP_THOUGHT_SIGNATURE if is_first_function_call else None,
                        )
                    )
                    is_first_function_call = False
                elif is_tool_result_param(block):
                    call_id = block.get("tool_use_id")
                    name = tool_name_by_call_id.get(cast(str, call_id), "") or str(call_id or "unknown")
                    parts.append(
                        Part(
                            function_response=FunctionResponse(
                                id=call_id if isinstance(call_id, str) else None,
                                name=name,
                                response=_tool_response_payload(
                                    block.get("content"), is_error=block.get("is_error") is True
                                ),
                            )
                        )
                    )
                else:
                    raise ValueError(f"Unsupported content block type: {type(block)}")

        contents.append(Content(role="model" if message["role"] == "assistant" else "user", parts=parts))

    return cast(ContentListUnion, contents)
