"""Images an LLM judge sees next to the transcript that refers to them as `[image N]`."""

import re
import base64
from collections import Counter
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Literal

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.storage.object_storage import ObjectStorageError

from products.ai_observability.backend.facade.api import BlobPointer
from products.ai_observability.backend.llm.images import IMAGE_MIME_TYPES, MAX_IMAGE_BYTES, ImagePart, image_transport
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock, MediaMarker

logger = structlog.get_logger(__name__)

JUDGE_IMAGES_FLAG = "llm-analytics-judge-images"

# Each image costs tokens on the customer's key, and above 20 images Anthropic tightens its per-image size limit.
MAX_IMAGES = 20
# Bytes sent inline in one judge request. Links don't count: the provider downloads them.
MAX_INLINE_BYTES = 15_000_000
# Covers the judge call and its retries. Sign right before the call: a link signed with temporary
# AWS credentials stops working when the credentials expire.
PRESIGNED_URL_SECONDS = 15 * 60

Outcome = Literal["link", "inline", "too_large", "unavailable"]

_NOT_ATTACHED_LABELS: dict[Outcome, str] = {
    "too_large": "not attached, too large",
    "unavailable": "could not be attached",
}


_NUMBERED_MARKER_RE = re.compile(r"\[image \d+\]")


@frozen
class ImagePrompt:
    """The judge transcript with `[image N]` markers, and the images those markers refer to."""

    text: str
    images: "JudgeImages"

    def unnumbered_text(self) -> str:
        """The transcript for a judge call that sends no images, so no marker points at a missing image."""
        return _NUMBERED_MARKER_RE.sub("[image]", self.text)


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
        mime_type = _normalize_mime_type(media.mime_type or (pointer.mime_type if pointer else None))
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
        attachments: dict[int, _Attachment] = {}
        inline_bytes = 0
        for image in reversed(ranked[-MAX_IMAGES:]):
            attachment = self._attach(image, provider, model, MAX_INLINE_BYTES - inline_bytes)
            inline_bytes += attachment.inline_bytes
            attachments[image.number] = attachment

        parts: list[Any] = [{"type": "text", "text": "The transcript refers to these images as [image N]."}]
        outcomes: Counter[str] = Counter()
        for image in images:
            if image.number not in attachments:
                continue
            attachment = attachments[image.number]
            outcomes[attachment.outcome] += 1
            if attachment.part is None:
                label = _NOT_ATTACHED_LABELS[attachment.outcome]
                parts.append({"type": "text", "text": f"Image {image.number}: {label}."})
            else:
                parts.extend([{"type": "text", "text": f"Image {image.number}:"}, attachment.part])
        # One line, not one per image: it sits outside the transcript's text budget.
        if over_limit := len(images) - len(attachments):
            outcomes["over_limit"] = over_limit
            parts.append({"type": "text", "text": f"Images not attached, over the judge's image limit: {over_limit}."})
        parts.append({"type": "text", "text": user_prompt})
        logger.info("judge_images_attached", provider=provider, model=model, inline_bytes=inline_bytes, **outcomes)
        return parts

    def _attach(self, image: _Image, provider: str, model: str, inline_budget: int) -> _Attachment:
        transport = image_transport(provider, model, image.mime_type)
        if transport is None:
            return _Attachment(outcome="unavailable")
        provider_limit = MAX_IMAGE_BYTES.get(provider)
        if image.pointer is None:
            if len(image.base64_data or "") * 3 // 4 > min(inline_budget, provider_limit or inline_budget):
                return _Attachment(outcome="too_large")
            try:
                data = base64.b64decode(image.base64_data or "", validate=True)
            except ValueError:  # binascii.Error, or a non-ASCII string
                return _Attachment(outcome="unavailable")
            return _Attachment(
                outcome="inline", part=ImagePart(mime_type=image.mime_type, data=data), inline_bytes=len(data)
            )
        limits = [
            limit for limit in (inline_budget if transport == "inline" else None, provider_limit) if limit is not None
        ]
        try:
            return self._attach_blob(image, image.pointer, transport, min(limits, default=None))
        except ObjectStorageError:
            return _Attachment(outcome="unavailable")

    def _attach_blob(
        self, image: _Image, pointer: BlobPointer, transport: Literal["url", "inline"], max_bytes: int | None
    ) -> _Attachment:
        stored_size = 0
        if max_bytes is not None:
            # Check the stored size first, so an oversized blob is never downloaded or sent.
            size = pointer.stored_size(self._team_id)
            if size is None:
                return _Attachment(outcome="unavailable")
            if size > max_bytes:
                return _Attachment(outcome="too_large")
            stored_size = size
        if transport == "url":
            url = pointer.presigned_url(self._team_id, PRESIGNED_URL_SECONDS)
            if url is None:
                return _Attachment(outcome="unavailable")
            return _Attachment(outcome="link", part=ImagePart(mime_type=image.mime_type, url=url))
        # ponytail: sequential reads, a thread pool if traces with many images get slow
        data = pointer.read(self._team_id)
        if data is None:
            return _Attachment(outcome="unavailable")
        part = ImagePart(mime_type=image.mime_type, data=data)
        return _Attachment(outcome="inline", part=part, inline_bytes=stored_size)


def _normalize_mime_type(mime_type: str | None) -> str | None:
    if mime_type is None:
        return None
    normalized = mime_type.strip().lower()
    return "image/jpeg" if normalized == "image/jpg" else normalized


@lru_cache(maxsize=4096)
def _project_uuid(team_id: int) -> str | None:
    project_uuid = Team.objects.filter(pk=team_id).values_list("uuid", flat=True).first()
    return str(project_uuid) if project_uuid else None


def judge_sees_images(evaluation: dict[str, Any]) -> bool:
    if evaluation["evaluation_config"].get("include_media") is False:
        return False
    # Local evaluation keeps the check off the network. An inconclusive result means off.
    try:
        # Team ids repeat across regions and self-hosted instances, so the flag targets the project uuid.
        project_uuid = _project_uuid(evaluation["team_id"])
        if project_uuid is None:
            return False
        return bool(
            posthoganalytics.feature_enabled(
                JUDGE_IMAGES_FLAG,
                project_uuid,
                groups={"project": project_uuid},
                group_properties={"project": {"id": str(evaluation["team_id"]), "uuid": project_uuid}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def build_image_prompt(
    evaluation: dict[str, Any], plain_prompt: str | None, render: Callable[[MediaMarker], str | None]
) -> ImagePrompt | None:
    """The marked prompt and its images, or None when this judge run gets the plain prompt only.

    `render` builds the same transcript as the plain prompt, with media blocks rendered by the marker it gets.
    """
    if not judge_sees_images(evaluation):
        return None
    images = JudgeImages(evaluation["team_id"])
    marked = render(images.marker)
    return ImagePrompt(text=marked, images=images) if marked is not None and marked != plain_prompt else None
