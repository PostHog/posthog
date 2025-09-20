from typing import Optional

from django.conf import settings
from django.db import models

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

    def get_absolute_url(self) -> str:
        return absolute_uri(f"/uploaded_media/{self.id}")

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
    path_parts: list[str] = [
        settings.OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER,
        f"team-{uploaded_media.team.pk}",
        f"media-{uploaded_media.pk}",
    ]
    object_path = "/".join(path_parts)
    object_storage.write(object_path, content)
    uploaded_media.media_location = object_path
    uploaded_media.save(update_fields=["media_location"])
