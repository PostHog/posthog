from collections.abc import Callable
from typing import Any, Literal

from products.ai_observability.backend.llm.types import ImagePart

ImageTransport = Literal["url", "inline"]

IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
# Providers whose image blocks take a link that they download themselves.
_URL_PROVIDERS = frozenset({"openai", "azure_openai", "anthropic", "openrouter", "gemini"})


def image_transport(provider: str, model: str, mime_type: str) -> ImageTransport | None:
    """How a provider accepts an image of this type: a link, inline base64, or not at all."""
    if mime_type not in IMAGE_MIME_TYPES:
        return None
    if provider == "gemini":
        if mime_type == "image/gif":
            return None
        # The Gemini 2.0 family can't fetch external links.
        return "inline" if model.startswith("gemini-2.0") else "url"
    return "url" if provider in _URL_PROVIDERS else "inline"


def convert_image_parts(messages: list[dict[str, Any]], convert: Callable[[ImagePart], Any]) -> list[dict[str, Any]]:
    """Replace each ImagePart in the messages' content lists with the provider block that `convert` returns."""
    return [
        {**message, "content": [convert(part) if isinstance(part, ImagePart) else part for part in message["content"]]}
        if isinstance(message.get("content"), list)
        else message
        for message in messages
    ]
