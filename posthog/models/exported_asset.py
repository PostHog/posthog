import secrets
from datetime import timedelta
from typing import List, Optional

import structlog
from django.conf import settings
from django.db import models
from django.http import HttpResponse
from django.utils.text import slugify
from sentry_sdk import capture_exception

from posthog.jwt import PosthogJwtAudience, decode_jwt, encode_jwt
from posthog.models.utils import UUIDT
from posthog.settings import DEBUG
from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError
from posthog.utils import absolute_uri

logger = structlog.get_logger(__name__)

PUBLIC_ACCESS_TOKEN_EXP_DAYS = 365
MAX_AGE_CONTENT = 86400  # 1 day


def get_default_access_token() -> str:
    return secrets.token_urlsafe(22)


class ExportedAsset(models.Model):
    class ExportFormat(models.TextChoices):
        PNG = "image/png", "image/png"
        PDF = "application/pdf", "application/pdf"
        CSV = "text/csv", "text/csv"

    # Relations
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("posthog.Dashboard", on_delete=models.CASCADE, null=True)
    insight = models.ForeignKey("posthog.Insight", on_delete=models.CASCADE, null=True)

    # Content related fields
    export_format: models.CharField = models.CharField(max_length=16, choices=ExportFormat.choices)
    content: models.BinaryField = models.BinaryField(null=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)
    # for example holds filters for CSV exports
    export_context: models.JSONField = models.JSONField(null=True, blank=True)
    # path in object storage or some other location identifier for the asset
    # 1000 characters would hold a 20 UUID forward slash separated path with space to spare
    content_location: models.TextField = models.TextField(null=True, blank=True, max_length=1000)

    # DEPRECATED: We now use JWT for accessing assets
    access_token: models.CharField = models.CharField(
        max_length=400, null=True, blank=True, default=get_default_access_token
    )

    @property
    def has_content(self):
        return self.content is not None or self.content_location is not None

    @property
    def filename(self):
        ext = self.export_format.split("/")[1]
        filename = "export"

        if self.export_context and self.export_context.get("filename"):
            filename = slugify(self.export_context.get("filename"))
        elif self.dashboard and self.dashboard.name is not None:
            filename = f"{filename}-{slugify(self.dashboard.name)}"
        elif self.insight:
            filename = f"{filename}-{slugify(self.insight.name or self.insight.derived_name)}"

        filename = f"{filename}.{ext}"

        return filename

    @property
    def file_ext(self):
        return self.export_format.split("/")[1]

    def get_analytics_metadata(self):
        return {"export_format": self.export_format, "dashboard_id": self.dashboard_id, "insight_id": self.insight_id}

    def get_public_content_url(self, expiry_delta: Optional[timedelta] = None):
        token = get_public_access_token(self, expiry_delta)
        return absolute_uri(f"/exporter/{self.filename}?token={token}")


def get_public_access_token(asset: ExportedAsset, expiry_delta: Optional[timedelta] = None) -> str:
    if not expiry_delta:
        expiry_delta = timedelta(days=PUBLIC_ACCESS_TOKEN_EXP_DAYS)
    return encode_jwt({"id": asset.id}, expiry_delta=expiry_delta, audience=PosthogJwtAudience.EXPORTED_ASSET,)


def asset_for_token(token: str) -> ExportedAsset:
    info = decode_jwt(token, audience=PosthogJwtAudience.EXPORTED_ASSET)
    asset = ExportedAsset.objects.select_related("dashboard", "insight").get(pk=info["id"])

    return asset


def get_content_response(asset: ExportedAsset, download: bool = False):
    content = asset.content
    if not content and asset.content_location:
        content = object_storage.read_bytes(asset.content_location)

    res = HttpResponse(content, content_type=asset.export_format)
    if download:
        res["Content-Disposition"] = f'attachment; filename="{asset.filename}"'

    if not DEBUG:
        res["Cache-Control"] = f"max-age={MAX_AGE_CONTENT}"

    return res


def save_content(exported_asset: ExportedAsset, content: bytes) -> None:
    try:
        if settings.OBJECT_STORAGE_ENABLED:
            save_content_to_object_storage(exported_asset, content)
        else:
            save_content_to_exported_asset(exported_asset, content)
    except ObjectStorageError as ose:
        capture_exception(ose)
        logger.error(
            "exported_asset.object-storage-error", exported_asset_id=exported_asset.id, exception=ose, exc_info=True
        )
        save_content_to_exported_asset(exported_asset, content)


def save_content_to_exported_asset(exported_asset: ExportedAsset, content: bytes) -> None:
    exported_asset.content = content
    exported_asset.save(update_fields=["content"])


def save_content_to_object_storage(exported_asset: ExportedAsset, content: bytes) -> None:
    path_parts: List[str] = [
        settings.OBJECT_STORAGE_EXPORTS_FOLDER,
        exported_asset.export_format.split("/")[1],
        f"team-{exported_asset.team.id}",
        f"task-{exported_asset.id}",
        str(UUIDT()),
    ]
    object_path = f'/{"/".join(path_parts)}'
    object_storage.write(object_path, content)
    exported_asset.content_location = object_path
    exported_asset.save(update_fields=["content_location"])
