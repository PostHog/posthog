import re
from typing import Optional

from django.conf import settings
from django.db import models

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.utils import RootTeamManager, RootTeamMixin, UUIDTModel
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.utils import absolute_uri

UPLOADED_MEDIA_UUID_PATTERN = re.compile(
    r"/uploaded_media/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE
)

logger = structlog.get_logger(__name__)


class ObjectStorageUnavailable(Exception):
    pass


class UploadedMediaManager(RootTeamManager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True)


class UploadedMedia(UUIDTModel, RootTeamMixin):
    objects = UploadedMediaManager()  # type: ignore[misc]
    objects_including_soft_deleted: models.Manager["UploadedMedia"] = models.Manager()

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    project = models.ForeignKey("Project", on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    # path in object storage or some other location identifier for the asset
    # 1000 characters would hold a 20 UUID forward slash separated path with space to spare
    media_location = models.TextField(null=True, blank=True, max_length=1000)
    content_type = models.TextField(null=True, blank=True, max_length=100)
    file_name = models.TextField(null=True, blank=True, max_length=1000)
    deleted = models.BooleanField(default=False)

    def get_absolute_url(self) -> str:
        return absolute_uri(f"/uploaded_media/{self.id}")

    @classmethod
    def extract_media_uuids(cls, text_body: str) -> set[str]:
        return set(UPLOADED_MEDIA_UUID_PATTERN.findall(text_body))

    @classmethod
    def _uuids_referenced_by_other_texts(cls, team_id: int, exclude_text_ids: Optional[list[int]] = None) -> set[str]:
        from posthog.models.dashboard_tile import Text

        qs = Text.objects.filter(team_id=team_id, body__contains="/uploaded_media/")
        if exclude_text_ids:
            qs = qs.exclude(id__in=exclude_text_ids)
        referenced: set[str] = set()
        for body in qs.values_list("body", flat=True):
            if body:
                referenced.update(cls.extract_media_uuids(body))
        return referenced

    @classmethod
    def soft_delete_for_removed_images(
        cls, old_body: str, new_body: Optional[str], team_id: int, exclude_text_ids: Optional[list[int]] = None
    ) -> None:
        old_uuids = cls.extract_media_uuids(old_body)
        new_uuids = cls.extract_media_uuids(new_body) if new_body else set()
        removed_uuids = old_uuids - new_uuids
        if not removed_uuids:
            return
        still_referenced = cls._uuids_referenced_by_other_texts(team_id, exclude_text_ids)
        to_delete = removed_uuids - still_referenced
        if to_delete:
            cls.objects_including_soft_deleted.filter(id__in=to_delete, team_id=team_id, deleted=False).update(
                deleted=True
            )

    @classmethod
    def soft_delete_for_text_bodies(
        cls, bodies: list[str], team_id: int, exclude_text_ids: Optional[list[int]] = None
    ) -> None:
        all_uuids: set[str] = set()
        for body in bodies:
            all_uuids.update(cls.extract_media_uuids(body))
        if not all_uuids:
            return
        still_referenced = cls._uuids_referenced_by_other_texts(team_id, exclude_text_ids)
        to_delete = all_uuids - still_referenced
        if to_delete:
            cls.objects_including_soft_deleted.filter(id__in=to_delete, team_id=team_id, deleted=False).update(
                deleted=True
            )

    @classmethod
    def restore_for_text_bodies(cls, bodies: list[str], team_id: int) -> None:
        all_uuids: set[str] = set()
        for body in bodies:
            all_uuids.update(cls.extract_media_uuids(body))
        if all_uuids:
            cls.objects_including_soft_deleted.filter(id__in=all_uuids, team_id=team_id, deleted=True).update(
                deleted=False
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
    path_parts: list[str] = [
        settings.OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER,
        f"team-{uploaded_media.team.pk}",
        f"media-{uploaded_media.pk}",
    ]
    object_path = "/".join(path_parts)
    object_storage.write(object_path, content)
    uploaded_media.media_location = object_path
    uploaded_media.save(update_fields=["media_location"])
