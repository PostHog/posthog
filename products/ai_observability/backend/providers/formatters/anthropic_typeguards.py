from typing import Any, TypeGuard

from anthropic.types import (
    Base64ImageSourceParam,
    ImageBlockParam,
    TextBlockParam,
    ToolResultBlockParam,
    ToolUseBlockParam,
    URLImageSourceParam,
)


def is_string(part: Any) -> TypeGuard[str]:
    return isinstance(part, str)


def is_tool_result_param(part: Any) -> TypeGuard[ToolResultBlockParam]:
    return isinstance(part, dict) and part.get("type") == "tool_result"


def is_tool_use_param(part: Any) -> TypeGuard[ToolUseBlockParam]:
    return isinstance(part, dict) and part.get("type") == "tool_use"


def is_text_block_param(part: Any) -> TypeGuard[TextBlockParam]:
    return isinstance(part, dict) and part.get("type") == "text"


def is_image_block_param(part: Any) -> TypeGuard[ImageBlockParam]:
    return isinstance(part, dict) and part.get("type") == "image"


def is_base64_image_param(part: Any) -> TypeGuard[Base64ImageSourceParam]:
    return isinstance(part, dict) and part.get("type") == "base64"


def is_url_image_param(part: Any) -> TypeGuard[URLImageSourceParam]:
    return isinstance(part, dict) and part.get("type") == "url"
