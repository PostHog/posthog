"""Images an LLM judge sees next to the transcript that refers to them as `[image N]`."""

import base64
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.ai_observability.backend.ai_blobs import BlobPointer
from products.ai_observability.backend.llm.images import IMAGE_MIME_TYPES, ImagePart, image_transport
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock

# Each image costs tokens on the customer's key, and above 20 images Anthropic tightens its per-image size limit.
MAX_IMAGES = 20
# Bytes sent inline in one judge request. A link has no cap here: the provider downloads it and applies its own limits.
MAX_INLINE_BYTES = 15_000_000
# Covers the judge call and its retries. Sign right before the call: a link signed with temporary
# AWS credentials stops working when the credentials expire.
PRESIGNED_URL_SECONDS = 15 * 60

OVER_LIMIT_MARKER = "[image: not attached, over the judge's image limit]"


@frozen
class _Image:
    number: int
    mime_type: str
    size: int
    # An offloaded image has a pointer, a small one stays inline as base64.
    pointer: BlobPointer | None
    base64_data: str | None


class JudgeImages:
    """Numbers the images found while formatting a transcript, then attaches them to the judge request."""

    def __init__(self, team_id: int) -> None:
        self._team_id = team_id
        self._images: list[_Image] = []
        self._numbers: dict[str, int] = {}

    def marker(self, media: MediaBlock) -> str:
        pointer = BlobPointer.parse(media.url) if media.url else None
        mime_type = media.mime_type or (pointer.mime_type if pointer else None)
        # Links from the customer's app keep a plain marker: we never fetch them.
        key = pointer.sha256 if pointer else media.base64_data
        if media.modality != "image" or mime_type not in IMAGE_MIME_TYPES or key is None:
            return media.marker()
        if (number := self._numbers.get(key)) is not None:
            return f"[image {number}]"

        if len(self._images) >= MAX_IMAGES:
            return OVER_LIMIT_MARKER
        number = len(self._images) + 1
        size = (pointer.size if pointer else None) or len(media.base64_data or "") * 3 // 4
        self._numbers[key] = number
        self._images.append(
            _Image(number=number, mime_type=mime_type, size=size, pointer=pointer, base64_data=media.base64_data)
        )
        return f"[image {number}]"

    def content(self, user_prompt: str, provider: str, model: str) -> str | list[Any]:
        """The user message content: each referenced image under its label, then the transcript."""
        # Line sampling can drop a marker from a long transcript, and then its image only costs tokens.
        images = [image for image in self._images if f"[image {image.number}]" in user_prompt]
        if not images:
            return user_prompt

        parts: list[Any] = [{"type": "text", "text": "The transcript refers to these images as [image N]."}]
        inline_bytes = 0
        for image in images:
            transport = image_transport(provider, model, image.mime_type)
            if transport is not None and (transport == "inline" or image.pointer is None):
                if inline_bytes + image.size > MAX_INLINE_BYTES:
                    parts.append({"type": "text", "text": f"Image {image.number}: not attached, too large."})
                    continue
                inline_bytes += image.size
            part = self._image_part(image, transport)
            if part is None:
                parts.append({"type": "text", "text": f"Image {image.number}: could not be attached."})
            else:
                parts.extend([{"type": "text", "text": f"Image {image.number}:"}, part])
        parts.append({"type": "text", "text": user_prompt})
        return parts

    def _image_part(self, image: _Image, transport: Literal["url", "inline"] | None) -> ImagePart | None:
        if transport is None:
            return None
        if image.pointer is None:
            return ImagePart(mime_type=image.mime_type, base64_data=image.base64_data)
        if transport == "url":
            url = image.pointer.presigned_url(self._team_id, PRESIGNED_URL_SECONDS)
            return ImagePart(mime_type=image.mime_type, url=url) if url else None
        # ponytail: sequential reads, a thread pool if traces with many images get slow
        data = image.pointer.read(self._team_id)
        return ImagePart(mime_type=image.mime_type, base64_data=base64.b64encode(data).decode()) if data else None
