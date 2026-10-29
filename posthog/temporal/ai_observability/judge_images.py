"""Images an LLM judge sees next to the transcript that refers to them as `[image N]`."""

import base64
from collections import Counter
from typing import Any, Literal

import structlog

from posthog.dataclasses import frozen

from products.ai_observability.backend.facade.api import BlobPointer
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
class ImagePrompt:
    """The judge transcript with `[image N]` markers, and the images those markers refer to."""

    text: str
    images: "JudgeImages"


@frozen
class _Attachment:
    outcome: Outcome
    part: ImagePart | None = None
    inline_bytes: int = 0


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

        # Keep the images referenced last: the newest input and the graded output, even when it repeats an old image.
        ranked = sorted(images, key=lambda image: user_prompt.rfind(f"[image {image.number}]"))
        attachable = {image.number for image in ranked[-MAX_IMAGES:]}
        parts: list[Any] = [{"type": "text", "text": "The transcript refers to these images as [image N]."}]
        outcomes: Counter[str] = Counter()
        inline_bytes = 0
        for image in images:
            attachment = (
                self._attach(image, provider, model, MAX_INLINE_BYTES - inline_bytes)
                if image.number in attachable
                else _Attachment(outcome="over_limit")
            )
            inline_bytes += attachment.inline_bytes
            outcomes[attachment.outcome] += 1
            if attachment.part is None:
                label = _NOT_ATTACHED_LABELS[attachment.outcome]
                parts.append({"type": "text", "text": f"Image {image.number}: {label}."})
            else:
                parts.extend([{"type": "text", "text": f"Image {image.number}:"}, attachment.part])
        parts.append({"type": "text", "text": user_prompt})
        logger.info("judge_images_attached", provider=provider, model=model, inline_bytes=inline_bytes, **outcomes)
        return parts

    def _attach(self, image: _Image, provider: str, model: str, inline_budget: int) -> _Attachment:
        transport = image_transport(provider, model, image.mime_type)
        if transport is None:
            return _Attachment(outcome="unavailable")
        if image.pointer is None:
            size = len(image.base64_data or "") * 3 // 4
            if size > inline_budget:
                return _Attachment(outcome="too_large")
            part = ImagePart(mime_type=image.mime_type, base64_data=image.base64_data)
            return _Attachment(outcome="inline", part=part, inline_bytes=size)
        if transport == "url":
            url = image.pointer.presigned_url(self._team_id, PRESIGNED_URL_SECONDS)
            if url is None:
                return _Attachment(outcome="unavailable")
            return _Attachment(outcome="link", part=ImagePart(mime_type=image.mime_type, url=url))
        # Check the stored size before downloading, so an oversized blob never reaches worker memory.
        stored_size = image.pointer.stored_size(self._team_id)
        if stored_size is None:
            return _Attachment(outcome="unavailable")
        if stored_size > inline_budget:
            return _Attachment(outcome="too_large")
        # ponytail: sequential reads, a thread pool if traces with many images get slow
        data = image.pointer.read(self._team_id)
        if data is None:
            return _Attachment(outcome="unavailable")
        part = ImagePart(mime_type=image.mime_type, base64_data=base64.b64encode(data).decode())
        return _Attachment(outcome="inline", part=part, inline_bytes=stored_size)
