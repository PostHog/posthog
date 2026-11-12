"""Shared attachment helpers for conversations channels (email, Slack, etc.)."""

import re
from collections.abc import Iterator
from typing import Any

from django.conf import settings

import structlog

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.uploaded_media import (
    UploadedMedia,
    is_inline_safe_content_type,
    save_content_to_object_storage,
    sniff_image_content_type,
)
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

logger = structlog.get_logger(__name__)

CONVERSATIONS_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MiB
MAX_ATTACHMENTS_PER_MESSAGE = 20
# Mailgun rejects a message over 25 MB, and base64 makes each attached file a third larger.
# Files past this budget stay links in the email body, so one large file cannot fail the whole reply.
EMAIL_MAX_ATTACHED_BYTES = 15 * 1024 * 1024

MAX_FILENAME_LENGTH = 255
# Keep word chars, whitespace and a small punctuation set. Notably drops "[", "]"
# and "!" so an attacker-controlled filename can't inject markdown link/image
# syntax when we render it as `[name](url)` / `![name](url)`.
_FILENAME_STRIP_RE = re.compile(r"[^\w\s\-.,()]+")
_REHOSTED_MEDIA_URL_RE = re.compile(
    r"/uploaded_media/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


def sanitize_attachment_filename(name: str | None) -> str:
    """Strip potentially dangerous characters from an inbound attachment filename.

    Names arrive from untrusted sources (email, Slack, Teams) and flow into
    markdown/rich content, object storage, and Content-Disposition headers.
    """
    name = (name or "").strip().replace("/", "_").replace("\\", "_")
    name = _FILENAME_STRIP_RE.sub("", name)
    if len(name) > MAX_FILENAME_LENGTH:
        name = name[:MAX_FILENAME_LENGTH]
    return name or "attachment"


def resolve_attachment_content_type(content: bytes, declared_content_type: str) -> str | None:
    """Return the content type to store for an attachment, or None when its bytes are not a valid image.

    The media endpoint serves only inline-safe types inline, so only those get a decode, which
    prevents serving disguised content as an image. For them the stored type comes from the
    decoded bytes, not from the sender's claim. The endpoint serves every other type, including
    image types such as TIFF or HEIC, as an opaque download, so those keep their declared type
    and are stored without a decode.
    """
    if not is_inline_safe_content_type(declared_content_type):
        return declared_content_type
    return sniff_image_content_type(content)


# Marks files that a support channel re-hosted. Ticket cleanup deletes only these, because a
# team file can also have no created_by (its uploader was removed) and can be linked from a message.
CONVERSATIONS_ATTACHMENT_MEDIA_PURPOSE = "conversations_attachment"


def save_file_to_uploaded_media(
    team: Team,
    file_name: str,
    content_type: str,
    content: bytes,
    *,
    validate_images: bool = True,
) -> str | None:
    """Persist a file to object storage via UploadedMedia.

    Returns the absolute URL on success, None on failure.
    """
    uploaded_media = save_uploaded_media(team, file_name, content_type, content, validate_images=validate_images)
    return uploaded_media.get_absolute_url() if uploaded_media else None


def save_uploaded_media(
    team: Team,
    file_name: str,
    content_type: str,
    content: bytes,
    *,
    validate_images: bool = True,
) -> UploadedMedia | None:
    """Persist a file to object storage via UploadedMedia, or return None on failure.

    Unless validate_images is False, stores the type that resolve_attachment_content_type
    returns, and rejects bytes that it finds invalid.
    """
    if not settings.OBJECT_STORAGE_ENABLED:
        logger.warning("conversations_attachment_no_object_storage", team_id=team.id)
        return None

    if validate_images:
        resolved_content_type = resolve_attachment_content_type(content, content_type)
        if resolved_content_type is None:
            logger.warning("conversations_attachment_invalid_image", team_id=team.id, file_name=file_name)
            return None
        content_type = resolved_content_type

    uploaded_media = UploadedMedia.objects.create(
        team=team,
        file_name=file_name,
        content_type=content_type,
        created_by=None,
        purpose=CONVERSATIONS_ATTACHMENT_MEDIA_PURPOSE,
    )
    try:
        save_content_to_object_storage(uploaded_media, content)
    except Exception as e:
        logger.warning(
            "conversations_attachment_storage_failed",
            team_id=team.id,
            uploaded_media_id=str(uploaded_media.id),
            file_name=file_name,
            error=str(e),
        )
        uploaded_media.delete()
        return None

    logger.info(
        "conversations_attachment_saved",
        team_id=team.id,
        uploaded_media_id=str(uploaded_media.id),
        file_name=file_name,
        content_type=content_type,
        bytes_size=len(content),
    )
    return uploaded_media


def attachment_link_label(attachment: dict[str, Any]) -> str:
    """Link text for a file attachment. Flags the ones that still live in Slack."""
    name = attachment.get("name") or "attachment"
    return f"{name} (open in Slack)" if attachment.get("unavailable") else name


def build_content_with_images(
    cleaned_text: str,
    rich_content: dict[str, Any] | None,
    images: list[dict[str, Any]],
    files: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """Merge extracted attachment metadata into plain-text content and rich_content doc.

    Images render as inline image nodes; non-image files render as download links.
    """
    files = files or []
    content = cleaned_text
    if not images and not files:
        return content, rich_content

    parts = [cleaned_text] if cleaned_text else []
    if images:
        parts.append("\n".join(f"![{img['name']}]({img['url']})" for img in images))
    if files:
        parts.append("\n".join(f"[{attachment_link_label(f)}]({f['url']})" for f in files))
    content = "\n\n".join(parts)

    if not isinstance(rich_content, dict):
        # Callers without upstream rich_content (e.g. Zendesk import) pass the text here only.
        # Seed it as paragraph nodes, or the UI — which renders rich_content exclusively — drops it.
        # Split on newlines so multi-line bodies keep their structure (the renderer collapses \n
        # within a single text node), matching how the Teams path builds its doc.
        seeded = [
            {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            for raw_line in cleaned_text.split("\n")
            if (line := raw_line.strip())
        ]
        rich_content = {"type": "doc", "content": seeded}
    rich_nodes = rich_content.setdefault("content", [])
    for img in images:
        rich_nodes.append(
            {
                "type": "image",
                "attrs": {"src": img["url"], "alt": img.get("name", "image")},
            }
        )
    for f in files:
        rich_nodes.append(
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": attachment_link_label(f),
                        "marks": [{"type": "link", "attrs": {"href": f["url"]}}],
                    }
                ],
            }
        )
    return content, rich_content


@frozen
class LinkedAttachment:
    file_name: str
    content_type: str
    content: bytes


def _iter_link_hrefs(node: object) -> Iterator[str]:
    if not isinstance(node, dict):
        return
    for mark in node.get("marks") or []:
        attrs = mark.get("attrs") if isinstance(mark, dict) and mark.get("type") == "link" else None
        href = attrs.get("href") if isinstance(attrs, dict) else None
        if isinstance(href, str):
            yield href
    children = node.get("content")
    if isinstance(children, list):
        for child in children:
            yield from _iter_link_hrefs(child)


def load_linked_attachments(team_id: int, rich_content: dict[str, Any] | None) -> list[LinkedAttachment]:
    """Read the re-hosted files that a reply links to, in document order, so an email can attach them.

    A file that is missing, cannot be read, or does not fit EMAIL_MAX_ATTACHED_BYTES is skipped,
    and the reply keeps only its link.
    """
    media_ids = list(
        dict.fromkeys(
            match.group(1).lower()
            for href in _iter_link_hrefs(rich_content)
            if (match := _REHOSTED_MEDIA_URL_RE.search(href))
        )
    )[:MAX_ATTACHMENTS_PER_MESSAGE]
    if not media_ids:
        return []

    media_by_id = {
        str(media.id): media
        for media in UploadedMedia.objects.filter(
            team_id=team_id, id__in=media_ids, purpose=CONVERSATIONS_ATTACHMENT_MEDIA_PURPOSE
        )
    }
    attachments: list[LinkedAttachment] = []
    remaining_bytes = EMAIL_MAX_ATTACHED_BYTES
    for media_id in media_ids:
        media = media_by_id.get(media_id)
        if media is None or not media.media_location:
            continue
        try:
            content = object_storage.read_bytes(media.media_location)
        except ObjectStorageError:
            logger.warning("conversations_linked_attachment_read_failed", team_id=team_id, media_id=media_id)
            continue
        if content is None:
            continue
        if len(content) > remaining_bytes:
            logger.info(
                "conversations_linked_attachment_over_budget", team_id=team_id, media_id=media_id, size=len(content)
            )
            continue
        remaining_bytes -= len(content)
        attachments.append(
            LinkedAttachment(
                file_name=media.file_name or "attachment",
                content_type=media.content_type or "application/octet-stream",
                content=content,
            )
        )
    return attachments


def discard_rehosted_attachments(team: Team, attachments: list[dict[str, Any]]) -> None:
    """Delete files that were re-hosted for a message that no ticket comment will reference."""
    media_ids = {
        match.group(1)
        for attachment in attachments
        if (match := _REHOSTED_MEDIA_URL_RE.search(attachment.get("url") or ""))
    }
    if not media_ids:
        return
    for media in UploadedMedia.objects.filter(
        team_id=team.id, id__in=media_ids, purpose=CONVERSATIONS_ATTACHMENT_MEDIA_PURPOSE
    ):
        if media.media_location:
            try:
                object_storage.delete(media.media_location)
            except ObjectStorageError:
                logger.warning("conversations_attachment_discard_failed", team_id=team.id, media_id=str(media.id))
                continue
        media.delete()
