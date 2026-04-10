"""Shared attachment helpers for conversations channels (email, Slack, etc.)."""

from io import BytesIO

from django.conf import settings

import structlog
from PIL import Image

from posthog.models.team import Team
from posthog.models.uploaded_media import UploadedMedia, save_content_to_object_storage

logger = structlog.get_logger(__name__)


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
