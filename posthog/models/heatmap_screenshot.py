from django.db import models

from posthog.models.utils import UUIDTModel


class HeatmapScreenshot(UUIDTModel):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Type(models.TextChoices):
        SCREENSHOT = "screenshot", "Screenshot"
        IFRAME = "iframe", "Iframe"
        RECORDING = "recording", "Recording"

    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    url = models.URLField(max_length=2000)
    data_url = models.URLField(max_length=2000, null=True, blank=True, help_text="URL for fetching heatmap data")
    width = models.IntegerField(default=1400)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.SCREENSHOT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)

    # Content storage (similar to ExportedAsset)
    content = models.BinaryField(null=True)
    content_location = models.TextField(null=True, blank=True, max_length=1000)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    # Error handling
    exception = models.TextField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "url", "width"]),
            models.Index(fields=["status"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["team", "url", "width", "type"], name="unique_team_url_width_type")
        ]

    @property
    def has_content(self) -> bool:
        return bool(self.content or self.content_location)

    def get_analytics_metadata(self) -> dict:
        return {
            "team_id": self.team_id,
            "url": self.url,
            "data_url": self.data_url,
            "width": self.width,
            "type": self.type,
            "status": self.status,
        }
