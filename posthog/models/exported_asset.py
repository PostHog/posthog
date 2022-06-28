import secrets
from datetime import timedelta
from typing import Optional

from django.db import models
from django.utils.text import slugify

from posthog.jwt import PosthogJwtAudience, decode_jwt, encode_jwt
from posthog.utils import absolute_uri

PUBLIC_ACCESS_TOKEN_EXP_DAYS = 365


def get_default_access_token() -> str:
    return secrets.token_urlsafe(22)


class ExportedAsset(models.Model):
    # deprecated
    class ExportType(models.TextChoices):
        DASHBOARD = "dashboard", "Dashboard"
        INSIGHT = "insight", "Insight"

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
    # for example holds filters for CSV exports
    export_context: models.JSONField = models.JSONField(null=True, blank=True)
    # path in object storage or some other location identifier for the asset
    # 1000 characters would hold a 20 UUID forward slash separated path with space to spare
    content_location: models.TextField = models.TextField(null=True, blank=True, max_length=1000)

    # Token for accessing the /exporter page
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

        if self.dashboard and self.dashboard.name is not None:
            filename = f"{filename}-{slugify(self.dashboard.name)}"
        if self.insight:
            filename = f"{filename}-{slugify(self.insight.name or self.insight.derived_name)}"

        filename = f"{filename}.{ext}"

        return filename

    @property
    def file_ext(self):
        return self.export_format.split("/")[1]

    def get_analytics_metadata(self):
        return {"export_format": self.export_format, "dashboard_id": self.dashboard_id, "insight_id": self.insight_id}

    @property
    def url(self):
        return absolute_uri(f"/exporter/{self.access_token}")

    def get_public_content_url(self, expiry_delta: Optional[timedelta] = None):
        token = get_public_access_token(self, expiry_delta)
        return absolute_uri(f"/exporter/{self.filename}?token={token}")


def get_public_access_token(asset: ExportedAsset, expiry_delta: Optional[timedelta] = None) -> str:
    if not expiry_delta:
        expiry_delta = timedelta(days=PUBLIC_ACCESS_TOKEN_EXP_DAYS)
    return encode_jwt({"id": asset.id}, expiry_delta=expiry_delta, audience=PosthogJwtAudience.EXPORTED_ASSET,)


def asset_for_token(token: str) -> ExportedAsset:
    info = decode_jwt(token, audience=PosthogJwtAudience.EXPORTED_ASSET)
    asset = ExportedAsset.objects.get(pk=info["id"])

    return asset
