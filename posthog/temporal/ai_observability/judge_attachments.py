"""Images, PDFs and audio an LLM judge gets next to the transcript, which refers to them by markers such as `[image N]`."""

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

from products.ai_observability.backend.facade.blobs import BlobPointer
from products.ai_observability.backend.llm.attachments import (
    AUDIO_FORMATS,
    IMAGE_MIME_TYPES,
    MAX_IMAGE_BYTES,
    MAX_PDF_BYTES,
    PDF_MIME_TYPE,
    AttachmentPart,
    attachment_transport,
)
from products.ai_observability.backend.text_repr.formatters.media_blocks import MediaBlock, MediaMarker

logger = structlog.get_logger(__name__)

JUDGE_ATTACHMENTS_FLAG = "llm-analytics-judge-images"

# Each attachment costs tokens on the customer's key, and above 20 images Anthropic tightens its per-image dimension limit.
MAX_ATTACHMENTS = 20
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


_NUMBERED_MARKER_RE = re.compile(r"\[(image|file|audio) \d+\]")


@frozen
class AttachmentPrompt:
    """The judge transcript with attachment markers, and the attachments they refer to."""

    text: str
    attachments: "JudgeAttachments"

    def unnumbered_text(self) -> str:
        """The transcript for a judge call that sends no attachments, so no marker points at a missing one."""
        return _NUMBERED_MARKER_RE.sub(r"[\1]", self.text)


@frozen
class _Attachment:
    outcome: Outcome
    part: AttachmentPart | None = None
    inline_bytes: int = 0


@frozen
class _Media:
    kind: Literal["image", "file", "audio"]
    number: int
    mime_type: str
    # An offloaded image has a pointer, a small one stays inline as base64.
    pointer: BlobPointer | None
    base64_data: str | None

    @property
    def marker(self) -> str:
        return f"[{self.kind} {self.number}]"

    @property
    def label(self) -> str:
        return f"{self.kind.capitalize()} {self.number}"


class JudgeAttachments:
    """Numbers the attachments found while formatting a transcript, then attaches them to the judge request."""

    def __init__(self, team_id: int) -> None:
        self._team_id = team_id
        self._media: list[_Media] = []
        self._media_by_key: dict[str, _Media] = {}
        self._counts: Counter[str] = Counter()
        # After one storage failure the rest would fail too, each after its own timeout and retry.
        self._storage_failed = False

    def marker(self, media: MediaBlock) -> str:
        pointer = BlobPointer.parse(media.url) if media.url else None
        mime_type = _normalize_mime_type(media.mime_type or (pointer.mime_type if pointer else None))
        # Links from the customer's app keep a plain marker: we never fetch them.
        key = pointer.sha256 if pointer else media.base64_data
        kind = _kind(media.modality, mime_type)
        if kind is None or mime_type is None or key is None:
            return media.marker()
        if (image := self._media_by_key.get(key)) is None:
            self._counts[kind] += 1
            image = self._media_by_key[key] = _Media(
                kind=kind,
                number=self._counts[kind],
                mime_type=mime_type,
                pointer=pointer,
                base64_data=media.base64_data,
            )
            self._media.append(image)
        return image.marker

    def content(self, user_prompt: str, provider: str, model: str) -> str | list[Any]:
        """The user message content: each referenced attachment under its label, then the transcript."""
        # Line sampling can drop a marker from a long transcript, and then its attachment only costs tokens.
        images = [image for image in self._media if image.marker in user_prompt]
        if not images:
            return user_prompt

        # Attachments this judge can't read take no slot, so they can't push out ones it can.
        readable = [image for image in images if attachment_transport(provider, model, image.mime_type) is not None]
        # Keep the images referenced last: the newest input and the graded output, even when it repeats an old image.
        ranked = sorted(readable, key=lambda image: user_prompt.rfind(image.marker))
        attachments: dict[str, _Attachment] = {}
        inline_bytes = 0
        for image in reversed(ranked[-MAX_ATTACHMENTS:]):
            attachment = self._attach(image, provider, model, MAX_INLINE_BYTES - inline_bytes)
            inline_bytes += attachment.inline_bytes
            attachments[image.marker] = attachment

        parts: list[Any] = [
            {"type": "text", "text": "The transcript refers to these attachments as [image N], [file N] or [audio N]."}
        ]
        outcomes: Counter[str] = Counter()
        for image in images:
            if image.marker not in attachments:
                continue
            attachment = attachments[image.marker]
            outcomes[f"{image.kind}_{attachment.outcome}"] += 1
            if attachment.part is None:
                label = _NOT_ATTACHED_LABELS[attachment.outcome]
                parts.append({"type": "text", "text": f"{image.label}: {label}."})
            else:
                parts.extend([{"type": "text", "text": f"{image.label}:"}, attachment.part])
        # One line each, not one per attachment: they sit outside the transcript's text budget.
        if over_limit := len(readable) - len(attachments):
            outcomes["over_limit"] = over_limit
            parts.append({"type": "text", "text": f"Not attached, over the judge's attachment limit: {over_limit}."})
        if unreadable := len(images) - len(readable):
            outcomes["unreadable"] = unreadable
            parts.append(
                {"type": "text", "text": f"Not attached, this judge can't read their file type: {unreadable}."}
            )
        parts.append({"type": "text", "text": user_prompt})
        logger.info("judge_attachments_attached", provider=provider, model=model, inline_bytes=inline_bytes, **outcomes)
        return parts

    def _attach(self, image: _Media, provider: str, model: str, inline_budget: int) -> _Attachment:
        transport = attachment_transport(provider, model, image.mime_type)
        if transport is None:
            return _Attachment(outcome="unavailable")
        provider_limit = MAX_PDF_BYTES if image.kind == "file" else MAX_IMAGE_BYTES.get(provider)
        if image.pointer is None:
            encoded = image.base64_data or ""
            if len(encoded) * 3 // 4 - encoded[-2:].count("=") > min(inline_budget, provider_limit or inline_budget):
                return _Attachment(outcome="too_large")
            try:
                data = base64.b64decode(image.base64_data or "", validate=True)
            except ValueError:  # binascii.Error, or a non-ASCII string
                return _Attachment(outcome="unavailable")
            return _Attachment(
                outcome="inline", part=AttachmentPart(mime_type=image.mime_type, data=data), inline_bytes=len(data)
            )
        if self._storage_failed:
            return _Attachment(outcome="unavailable")
        limits = [
            limit for limit in (inline_budget if transport == "inline" else None, provider_limit) if limit is not None
        ]
        try:
            return self._attach_blob(image, image.pointer, transport, min(limits, default=None))
        except ObjectStorageError:
            self._storage_failed = True
            return _Attachment(outcome="unavailable")

    def _attach_blob(
        self, image: _Media, pointer: BlobPointer, transport: Literal["url", "inline"], max_bytes: int | None
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
            return _Attachment(outcome="link", part=AttachmentPart(mime_type=image.mime_type, url=url))
        # ponytail: sequential reads, a thread pool if traces with many images get slow
        data = pointer.read(self._team_id)
        if data is None:
            return _Attachment(outcome="unavailable")
        part = AttachmentPart(mime_type=image.mime_type, data=data)
        return _Attachment(outcome="inline", part=part, inline_bytes=stored_size)


def _kind(modality: str, mime_type: str | None) -> Literal["image", "file", "audio"] | None:
    if modality == "image" and mime_type in IMAGE_MIME_TYPES:
        return "image"
    if modality == "audio" and mime_type in AUDIO_FORMATS:
        return "audio"
    if mime_type == PDF_MIME_TYPE:
        return "file"
    return None


_MIME_ALIASES = {
    "image/jpg": "image/jpeg",
    "audio/mp3": "audio/mpeg",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
}


def _normalize_mime_type(mime_type: str | None) -> str | None:
    if mime_type is None:
        return None
    normalized = mime_type.strip().lower()
    return _MIME_ALIASES.get(normalized, normalized)


@lru_cache(maxsize=4096)
def _project_uuid(team_id: int) -> str | None:
    project_uuid = Team.objects.filter(pk=team_id).values_list("uuid", flat=True).first()
    return str(project_uuid) if project_uuid else None


def judge_sees_attachments(evaluation: dict[str, Any]) -> bool:
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
                JUDGE_ATTACHMENTS_FLAG,
                project_uuid,
                groups={"project": project_uuid},
                group_properties={"project": {"id": str(evaluation["team_id"]), "uuid": project_uuid}},
                only_evaluate_locally=True,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def build_attachment_prompt(
    evaluation: dict[str, Any], plain_prompt: str | None, render: Callable[[MediaMarker], str | None]
) -> AttachmentPrompt | None:
    """The marked prompt and its attachments, or None when this judge run gets the plain prompt only.

    `render` builds the same transcript as the plain prompt, with media blocks rendered by the marker it gets.
    """
    if not judge_sees_attachments(evaluation):
        return None
    attachments = JudgeAttachments(evaluation["team_id"])
    marked = render(attachments.marker)
    return (
        AttachmentPrompt(text=marked, attachments=attachments)
        if marked is not None and marked != plain_prompt
        else None
    )
