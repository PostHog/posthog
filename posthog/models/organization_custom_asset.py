from typing import TYPE_CHECKING, Optional

from django.conf import settings
from django.db import models

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.models.user import User
from posthog.models.utils import CreatedMetaFields, UUIDModel
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.utils import absolute_uri

from .uploaded_media import ObjectStorageUnavailable

if TYPE_CHECKING:
    from posthog.models.organization import Organization

logger = structlog.get_logger(__name__)


class OrganizationCustomAsset(UUIDModel, CreatedMetaFields):
    """A custom image asset (logo, hog, etc.) attached to an organization so we can brand its UI.

    Assets are uploaded by staff through Django admin, stored in object storage, and served back
    through the unauthenticated /organization_custom_asset/<id> proxy view — mirroring UploadedMedia.
    """

    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="custom_assets",
        related_query_name="custom_asset",
    )
    # Free-form slot identifier (e.g. "logo", "hog", "sidebar-banner"). Not unique — an org can hold several.
    key = models.CharField(max_length=200)

    # path in object storage for the asset — same shape as UploadedMedia
    media_location = models.TextField(null=True, blank=True, max_length=1000)
    content_type = models.TextField(null=True, blank=True, max_length=100)
    file_name = models.TextField(null=True, blank=True, max_length=1000)

    def get_absolute_url(self) -> str:
        return absolute_uri(f"/organization_custom_asset/{self.id}")

    @classmethod
    def save_content(
        cls,
        organization: "Organization",
        created_by: Optional[User],
        key: str,
        file_name: str,
        content_type: str,
        content: bytes,
    ) -> Optional["OrganizationCustomAsset"]:
        try:
            asset = OrganizationCustomAsset.objects.create(
                organization=organization,
                created_by=created_by,
                key=key,
                file_name=file_name,
                content_type=content_type,
            )
            if settings.OBJECT_STORAGE_ENABLED:
                save_content_to_object_storage(asset, content)
            else:
                logger.error(
                    "organization_custom_asset.upload_attempted_without_object_storage_configured",
                    file_name=file_name,
                    organization=organization.pk,
                )
                raise ObjectStorageUnavailable()
            return asset
        except ObjectStorageError as ose:
            capture_exception(ose)
            logger.error(
                "organization_custom_asset.object-storage-error",
                file_name=file_name,
                organization=organization.pk,
                exception=ose,
                exc_info=True,
            )
            return None


def save_content_to_object_storage(asset: OrganizationCustomAsset, content: bytes) -> None:
    path_parts: list[str] = [
        settings.OBJECT_STORAGE_MEDIA_UPLOADS_FOLDER,
        f"organization-{asset.organization.pk}",
        f"custom-asset-{asset.pk}",
    ]
    object_path = "/".join(path_parts)
    object_storage.write(object_path, content)
    asset.media_location = object_path
    asset.save(update_fields=["media_location"])
