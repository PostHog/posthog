"""Images an LLM judge sees next to the transcript that refers to them as `[image N]`."""

import base64
from collections import Counter
from typing import Any, Literal

import structlog

from posthog.dataclasses import frozen

from products.ai_observability.backend.ai_blobs import BlobPointer
from products.ai_observability.backend.llm.images import IMAGE_MIME_TYPES, ImagePart, image_transport
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock

logger = structlog.get_logger(__name__)

# Each image costs tokens on the customer's key, and above 20 images Anthropic tightens its per-image size limit.
MAX_IMAGES = 20
# Bytes sent inline in one judge request. A link has no cap here: the provider downloads it and applies its own limits.
MAX_INLINE_BYTES = 15_000_000
# Covers the judge call and its retries. Sign right before the call: a link signed with temporary
# AWS credentials stops working when the credentials expire.
PRESIGNED_URL_SECONDS = 15 * 60

Outcome = Literal["link", "inline", "over_limit", "too_large", "unavailable"]

_NOT_ATTACHED_LABELS: dict[Outcome, str] = {
    "over_limit": "not attached, over the judge's image limit",
    "too_large": "not attached, too large",
    "unavailable": "could not be attached",
}


@frozen
class _Image:
    number: int
    mime_type: str
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
        if (number := self._numbers.get(key)) is None:
            number = self._numbers[key] = len(self._images) + 1
            self._images.append(
                _Image(number=number, mime_type=mime_type, pointer=pointer, base64_data=media.base64_data)
            )
        return f"[image {number}]"

    def content(self, user_prompt: str, provider: str, model: str) -> str | list[Any]:
        """The user message content: each referenced image under its label, then the transcript."""
        # Line sampling can drop a marker from a long transcript, and then its image only costs tokens.
        images = [image for image in self._images if f"[image {image.number}]" in user_prompt]
        if not images:
            return user_prompt

        # Numbers follow the transcript, input before output, so the last ones are the newest and the graded output.
        attachable = {image.number for image in images[-MAX_IMAGES:]}
        parts: list[Any] = [{"type": "text", "text": "The transcript refers to these images as [image N]."}]
        outcomes: Counter[str] = Counter()
        inline_bytes = 0
        for image in images:
            part = self._image_part(image, provider, model) if image.number in attachable else None
            size = len(part.base64_data) * 3 // 4 if part is not None and part.base64_data is not None else 0
            outcome: Outcome
            if image.number not in attachable:
                outcome = "over_limit"
            elif part is None:
                outcome = "unavailable"
            elif inline_bytes + size > MAX_INLINE_BYTES:
                # Counts the bytes actually read: the size in the pointer comes from the event.
                outcome = "too_large"
            else:
                outcome = "link" if part.url else "inline"
                inline_bytes += size
            outcomes[outcome] += 1
            if outcome in _NOT_ATTACHED_LABELS:
                parts.append({"type": "text", "text": f"Image {image.number}: {_NOT_ATTACHED_LABELS[outcome]}."})
            else:
                parts.extend([{"type": "text", "text": f"Image {image.number}:"}, part])
        parts.append({"type": "text", "text": user_prompt})
        logger.info("judge_images_attached", provider=provider, model=model, inline_bytes=inline_bytes, **outcomes)
        return parts

    def _image_part(self, image: _Image, provider: str, model: str) -> ImagePart | None:
        transport = image_transport(provider, model, image.mime_type)
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
