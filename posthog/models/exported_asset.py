import secrets

from django.conf import settings
from django.db import models
from django.utils.text import slugify


def get_default_access_token() -> str:
    return secrets.token_urlsafe(22)


class ExportedAsset(models.Model):
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

    # Token for accessing the /exporter page
    access_token: models.CharField = models.CharField(
        max_length=400, null=True, blank=True, default=get_default_access_token
    )

    @property
    def has_content(self):
        return self.content is not None

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

    def get_analytics_metadata(self):
        return {"export_format": self.export_format, "dashboard_id": self.dashboard_id, "insight_id": self.insight_id}

    @property
    def url(self):
        return f"{settings.SITE_URL}/exports/{self.access_token}"

    @property
    def public_content_url(self):
        # TODO: JWT tokenize this
        return f"{settings.SITE_URL}/exports/{self.id}"
