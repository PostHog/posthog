"""Shared attachment helpers for conversations channels (email, Slack, etc.)."""

import re
from io import BytesIO
from typing import Any

from django.conf import settings

import structlog
from PIL import Image

from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia, save_content_to_object_storage
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

CONVERSATIONS_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MiB
MAX_ATTACHMENTS_PER_MESSAGE = 20

# Per-file and combined caps for files an agent attaches to an outbound reply. The combined cap
# keeps the assembled MIME payload under the size most mailbox providers accept (~25 MiB).
MAX_OUTBOUND_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MiB
MAX_OUTBOUND_ATTACHMENTS_TOTAL_BYTES = 25 * 1024 * 1024  # 25 MiB

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


def is_valid_image(content: bytes) -> bool:
    """Verify bytes are a real image (prevents serving disguised malicious content).

    Uses the same PIL open + transpose check as the frontend upload API.
    """
    try:
        image = Image.open(BytesIO(content))
        image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        image.close()
        return True
    except Exception:
        return False


def save_uploaded_media(
    team: Team,
    file_name: str,
    content_type: str,
    content: bytes,
    *,
    validate_images: bool = True,
) -> UploadedMedia | None:
    """Persist a file to object storage and return the UploadedMedia row, or None on failure.

    For image content types, validates the bytes are a real image unless
    validate_images is False.
    """
    if not settings.OBJECT_STORAGE_ENABLED:
        logger.warning("conversations_attachment_no_object_storage", team_id=team.id)
        return None

    if validate_images and content_type.startswith("image/") and not is_valid_image(content):
        logger.warning("conversations_attachment_invalid_image", team_id=team.id, file_name=file_name)
        return None

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
    return uploaded_media


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
    media = save_uploaded_media(team, file_name, content_type, content, validate_images=validate_images)
    return media.get_absolute_url() if media is not None else None


def load_outbound_attachments(team_id: int, media_ids: list[str]) -> list[tuple[str, bytes, str]]:
    """Fetch stored attachments for an outbound email, scoped to the ticket's team.

    Returns ``(file_name, content, content_type)`` tuples in the requested order, skipping any
    row that's missing, unreadable, or would push the combined payload past the provider cap.
    Team-scoped by ``team_id`` so a comment can't reference another team's media.
    """
    if not media_ids:
        return []

    rows = {
        str(m.id): m
        for m in UploadedMedia.objects.filter(team_id=team_id, id__in=media_ids).exclude(media_location__isnull=True)
    }

    attachments: list[tuple[str, bytes, str]] = []
    total = 0
    for media_id in media_ids:
        media = rows.get(str(media_id))
        if media is None or media.media_location is None:
            continue
        content = object_storage.read_bytes(media.media_location, missing_ok=True)
        if content is None:
            logger.warning("conversations_outbound_attachment_missing", team_id=team_id, uploaded_media_id=media_id)
            continue
        total += len(content)
        if total > MAX_OUTBOUND_ATTACHMENTS_TOTAL_BYTES:
            logger.warning(
                "conversations_outbound_attachments_over_total_cap", team_id=team_id, uploaded_media_id=media_id
            )
            break
        attachments.append((media.file_name or "attachment", content, media.content_type or "application/octet-stream"))
    return attachments


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
        parts.append("\n".join(f"[{f['name']}]({f['url']})" for f in files))
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
                        "text": f.get("name", "attachment"),
                        "marks": [{"type": "link", "attrs": {"href": f["url"]}}],
                    }
                ],
            }
        )
    return content, rich_content
