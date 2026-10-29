import base64
from collections.abc import Callable
from dataclasses import field
from typing import Any, Literal

from posthog.dataclasses import frozen

IMAGE_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/webp", "image/gif"})
# Providers whose image blocks take a link that they download themselves.
_URL_PROVIDERS = frozenset({"openai", "azure_openai", "anthropic", "openrouter", "gemini"})
MAX_IMAGE_BYTES = {"anthropic": 5 * 1024 * 1024}


@frozen
class ImagePart:
    """An image in a message's content list. Each adapter converts it to its provider's image block.

    Set `url` for a link the provider downloads, or `data` for inline bytes.
    """

    mime_type: str
    url: str | None = None
    data: bytes | None = field(default=None, repr=False)

    def base64(self) -> str:
        return base64.b64encode(self.data or b"").decode()

    def data_uri(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64()}"


def image_transport(provider: str, model: str, mime_type: str) -> Literal["url", "inline"] | None:
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
