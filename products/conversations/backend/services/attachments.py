"""Shared attachment helpers for conversations channels (email, Slack, etc.)."""

import re
from typing import Any

from django.conf import settings

import structlog

from posthog.models.team import Team
from posthog.models.uploaded_media import (
    UploadedMedia,
    is_inline_safe_content_type,
    save_content_to_object_storage,
    sniff_image_content_type,
)

logger = structlog.get_logger(__name__)

CONVERSATIONS_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MiB
MAX_ATTACHMENTS_PER_MESSAGE = 20

MAX_FILENAME_LENGTH = 255
# Keep word chars, whitespace and a small punctuation set. Notably drops "[", "]"
# and "!" so an attacker-controlled filename can't inject markdown link/image
# syntax when we render it as `[name](url)` / `![name](url)`.
_FILENAME_STRIP_RE = re.compile(r"[^\w\s\-.,()]+")


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
    return uploaded_media.get_absolute_url()


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
