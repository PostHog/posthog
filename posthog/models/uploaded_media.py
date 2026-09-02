from datetime import timedelta
from typing import Optional

from django.conf import settings
from django.db import models
from django.db.models import Q

import structlog

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
MEDIA_PURPOSES = [MEDIA_PURPOSE_EMAIL]

# A pending row older than this is abandoned: the presigned URL it was created for expires in
# minutes, so nothing can complete it, and nothing else revisits it. Generous because the only
# cost of waiting is one unlisted row and its staged bytes.
ABANDONED_UPLOAD_AGE = timedelta(hours=24)


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
    ) -> Optional["UploadedMedia"]:
        try:
            media = UploadedMedia.objects.create(
                team=team,
                created_by=created_by,
                file_name=file_name,
                content_type=content_type,
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
            return None


def save_content_to_object_storage(uploaded_media: UploadedMedia, content: bytes) -> None:
    object_path = UploadedMedia.build_media_location(uploaded_media.team.pk, uploaded_media.pk)
    object_storage.write(object_path, content)
    uploaded_media.media_location = object_path
    uploaded_media.save(update_fields=["media_location"])
