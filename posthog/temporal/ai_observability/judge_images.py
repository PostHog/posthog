"""Images an LLM judge sees next to the transcript that refers to them as `[image N]`."""

import base64
from typing import Any

from posthog.dataclasses import frozen

from products.ai_observability.backend.ai_blobs import BlobPointer
from products.ai_observability.backend.llm.images import IMAGE_MIME_TYPES, image_transport
from products.ai_observability.backend.llm.types import ImagePart
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock

# Above 20 images Anthropic lowers its per-image size limit.
MAX_IMAGES = 20
# Inline base64 grows bytes by a third, so these fit 5 MB per image and Gemini's 20 MB per request.
MAX_IMAGE_BYTES = 3_500_000
MAX_TOTAL_BYTES = 15_000_000
# Covers the judge call and its retries. Sign right before the call: a link signed with temporary
# AWS credentials stops working when the credentials expire.
PRESIGNED_URL_SECONDS = 15 * 60

OVER_LIMIT_MARKER = "[image: not attached, over the judge's image limit]"


@frozen
class _Image:
    number: int
    mime_type: str
    media: MediaBlock
    pointer: BlobPointer | None


class JudgeImages:
    """Numbers the images found while formatting a transcript, then attaches them to the judge request."""

    def __init__(self, team_id: int) -> None:
        self._team_id = team_id
        self._images: list[_Image] = []
        self._numbers: dict[str, int] = {}
        self._total_bytes = 0

    def marker(self, media: MediaBlock) -> str:
        pointer = BlobPointer.parse(media.url) if media.url else None
        mime_type = media.mime_type or (pointer.mime_type if pointer else None)
        key = pointer.sha256 if pointer else media.url or media.base64_data
        if media.modality != "image" or mime_type not in IMAGE_MIME_TYPES or key is None:
            return media.marker()
        if (number := self._numbers.get(key)) is not None:
            return f"[image {number}]"

        size = (pointer.size if pointer else None) or len(media.base64_data or "") * 3 // 4
        if len(self._images) >= MAX_IMAGES or size > MAX_IMAGE_BYTES or self._total_bytes + size > MAX_TOTAL_BYTES:
            return OVER_LIMIT_MARKER
        self._total_bytes += size
        number = len(self._images) + 1
        self._numbers[key] = number
        self._images.append(_Image(number=number, mime_type=mime_type, media=media, pointer=pointer))
        return f"[image {number}]"

    def content(self, user_prompt: str, provider: str, model: str) -> str | list[Any]:
        """The user message content: each referenced image under its label, then the transcript."""
        # Line sampling can drop a marker from a long transcript, and then its image only costs tokens.
        images = [image for image in self._images if f"[image {image.number}]" in user_prompt]
        if not images:
            return user_prompt

        parts: list[Any] = [{"type": "text", "text": "The transcript refers to these images as [image N]."}]
        for image in images:
            part = self._image_part(image, provider, model)
            if part is None:
                parts.append({"type": "text", "text": f"Image {image.number}: could not be attached."})
            else:
                parts.extend([{"type": "text", "text": f"Image {image.number}:"}, part])
        parts.append({"type": "text", "text": user_prompt})
        return parts

    def _image_part(self, image: _Image, provider: str, model: str) -> ImagePart | None:
        transport = image_transport(provider, model, image.mime_type)
        if transport is None:
            return None
        if image.pointer is not None:
            if transport == "url":
                url = image.pointer.presigned_url(self._team_id, PRESIGNED_URL_SECONDS)
                return ImagePart(mime_type=image.mime_type, url=url) if url else None
            # ponytail: sequential reads, a thread pool if traces with many images get slow
            data = image.pointer.read(self._team_id)
            return ImagePart(mime_type=image.mime_type, base64_data=base64.b64encode(data).decode()) if data else None
        if image.media.base64_data is not None:
            return ImagePart(mime_type=image.mime_type, base64_data=image.media.base64_data)
        # A customer's own link: the provider may download it, but we never fetch it ourselves.
        return ImagePart(mime_type=image.mime_type, url=image.media.web_url) if transport == "url" else None
