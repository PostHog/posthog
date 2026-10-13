from datetime import timedelta
from io import BytesIO
from typing import Optional

from django.conf import settings
from django.db import models
from django.db.models import Q

import structlog
from PIL import Image

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import RootTeamMixin, UUIDTModel
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)


class ObjectStorageUnavailable(Exception):
    pass


# Libraries an image can be added to. The column stays free-text so adding a consumer is one
# line here, but the API accepts nothing outside this set: a typo would otherwise open a
# second library that nothing lists, and give the caller no sign that it had.
MEDIA_PURPOSE_EMAIL = "email"
MEDIA_PURPOSE_CANVAS = "canvas"
MEDIA_PURPOSES = [MEDIA_PURPOSE_EMAIL, MEDIA_PURPOSE_CANVAS]

# These uploads must never be served through the unauthenticated /uploaded_media route.
# Their owning product provides an authenticated download endpoint instead.
MEDIA_PURPOSE_DESKTOP_FEEDBACK = "desktop_feedback"
PRIVATE_MEDIA_PURPOSES = frozenset({MEDIA_PURPOSE_DESKTOP_FEEDBACK})

# A pending row older than this is abandoned: the presigned URL it was created for expires in
# minutes, so nothing can complete it, and nothing else revisits it. Generous because the only
# cost of waiting is one unlisted row and its staged bytes.
ABANDONED_UPLOAD_AGE = timedelta(hours=24)

# Content types safe to render inline in a browser when served from the
# unauthenticated /uploaded_media endpoint. Anything outside this set is
# served as a download with a generic content type so stored HTML/SVG/etc.
# cannot execute script in the application origin.
_INLINE_SAFE_CONTENT_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/gif",
        "image/webp",
        "image/avif",
        "image/bmp",
    }
)

# The Pillow formats behind the content types above. Image.open without formats= tries every
# format Pillow can parse, so pass this to decode only the formats that download() serves inline.
INLINE_SAFE_IMAGE_FORMATS = ("PNG", "JPEG", "GIF", "WEBP", "AVIF", "BMP")


def _normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    return value.split(";", 1)[0].strip().lower()


def is_inline_safe_content_type(content_type: str | None) -> bool:
    return _normalize_content_type(content_type) in _INLINE_SAFE_CONTENT_TYPES


# Guards against a decompression bomb: a small, highly-compressed file that decodes to an
# enormous bitmap. Checked from the header, before Pillow decodes the full image into memory.
_MAX_IMAGE_PIXELS = 50_000_000


def sniff_image_content_type(data: Optional[bytes]) -> Optional[str]:
    """Determine an image's real content type from its bytes — never trust a caller's claim.

    Accepts only what `download` will serve inline: storing a format that always comes back
    as an attachment gives the caller a URL no image tag can render. Returns None for
    anything else, so the caller rejects rather than stores a type that misdescribes the
    bytes.
    """
    if not data:
        return None
    try:
        with Image.open(BytesIO(data), formats=INLINE_SAFE_IMAGE_FORMATS) as image:
            width, height = image.size
            if width * height > _MAX_IMAGE_PIXELS:
                return None
            image.load()
            content_type = Image.MIME.get(image.format or "")
    except Exception:
        return None
    return content_type if content_type in _INLINE_SAFE_CONTENT_TYPES else None


class UploadedMedia(UUIDTModel, RootTeamMixin):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    # path in object storage or some other location identifier for the asset
    # 1000 characters would hold a 20 UUID forward slash separated path with space to spare
    media_location = models.TextField(null=True, blank=True, max_length=1000)
    content_type = models.TextField(null=True, blank=True, max_length=100)
    file_name = models.TextField(null=True, blank=True, max_length=1000)

    # Library membership. NULL means this row predates the media library (or was
    # uploaded for a use that isn't a library, e.g. a dashboard text card) and stays
    # invisible to library listing. A consumer sets this to its own tag (e.g. "email").
    purpose = models.CharField(null=True, blank=True, max_length=100)
    size_bytes = models.IntegerField(null=True, blank=True)
    # True from presigned upload start until the uploaded object is verified. A pending
    # row's bytes are unvetted, so it is never listed and never served.
    pending = models.BooleanField(default=False)

    class Meta:
        indexes = [
            # Serves the library list query: WHERE team_id = ? AND purpose = ? AND NOT pending
            # ORDER BY created_at DESC. Excludes the vast majority of rows (dashboard images,
            # toolbar screenshots, ...) that carry no purpose and are never listed.
            models.Index(
                fields=["team", "purpose", "-created_at"],
                name="uploadedmedia_lib_by_created",
                condition=Q(purpose__isnull=False, pending=False),
            ),
        ]

    def get_absolute_url(self) -> str:
        return absolute_uri(f"/uploaded_media/{self.id}")

    @staticmethod
    def build_media_location(team_id: int, media_id) -> str:
        return "/".join(
            [
                settings.OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER,
                f"team-{team_id}",
                f"media-{media_id}",
            ]
        )

    @staticmethod
    def build_staging_location(team_id: int, media_id) -> str:
        """The only key a presigned upload POST is ever signed for.

        That signature stays valid until it expires, and Django can't revoke it early, so
        anyone still holding the form can rewrite whatever it points at. Verified bytes
        therefore move to `build_media_location`, a key no caller was ever signed for."""
        return "/".join(
            [
                settings.OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER,
                f"team-{team_id}",
                "staging",
                str(media_id),
            ]
        )

    @classmethod
    def save_content(
        cls,
        team: Team,
        created_by: User,
        file_name: str,
        content_type: str,
        content: bytes,
        purpose: str | None = None,
    ) -> Optional["UploadedMedia"]:
        try:
            media = UploadedMedia.objects.create(
                team=team,
                created_by=created_by,
                file_name=file_name,
                content_type=content_type,
                purpose=purpose,
            )
            if settings.OBJECT_STORAGE_ENABLED:
                save_content_to_object_storage(media, content)
            else:
                logger.error(
                    "uploaded_media.upload_attempted_without_object_storage_configured",
                    file_name=file_name,
                    team=team.pk,
                )
                raise ObjectStorageUnavailable()
            return media
        except ObjectStorageError as ose:
            capture_exception(ose)
            logger.error(
                "uploaded_media.object-storage-error",
                file_name=file_name,
                team=team.pk,
                exception=ose,
                exc_info=True,
            )
            object_path = cls.build_media_location(media.team_id, media.pk)
            media.media_location = object_path
            media.pending = True
            media.save(update_fields=["media_location", "pending"])
            try:
                object_storage.delete(object_path)
            except ObjectStorageError:
                logger.warning(
                    "uploaded_media.failed_save_cleanup_failed",
                    media_id=str(media.pk),
                    team_id=media.team_id,
                    exc_info=True,
                )
            else:
                media.delete()
            return None


def save_content_to_object_storage(uploaded_media: UploadedMedia, content: bytes) -> None:
    object_path = UploadedMedia.build_media_location(uploaded_media.team.pk, uploaded_media.pk)
    object_storage.write(object_path, content)
    uploaded_media.media_location = object_path
    uploaded_media.save(update_fields=["media_location"])
