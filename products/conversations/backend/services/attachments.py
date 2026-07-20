"""Shared attachment helpers for conversations channels (email, Slack, etc.)."""

import re
from io import BytesIO
from typing import Any

from django.conf import settings

import structlog
from PIL import Image

from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia, save_content_to_object_storage

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
    return uploaded_media.get_absolute_url()


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
        rich_content = {"type": "doc", "content": []}
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
