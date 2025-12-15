from django.db import models

from posthog.models.utils import UUIDModel, UUIDTModel
from posthog.utils import generate_short_id


class SavedHeatmap(UUIDTModel):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    class Type(models.TextChoices):
        SCREENSHOT = "screenshot", "Screenshot"
        IFRAME = "iframe", "Iframe"
        RECORDING = "recording", "Recording"

    short_id = models.CharField(max_length=12, blank=True, default=generate_short_id)
    name = models.CharField(max_length=400, null=True, blank=True)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    url = models.URLField(max_length=2000)
    data_url = models.URLField(max_length=2000, null=True, blank=True, help_text="URL for fetching heatmap data")
    # Planned widths to generate for screenshot-type heatmaps
    target_widths = models.JSONField(default=list)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.SCREENSHOT)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)

    # Content moved to HeatmapSnapshot per width

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey("User", on_delete=models.SET_NULL, null=True, blank=True)

    # Error handling
    exception = models.TextField(null=True, blank=True)

    # Soft delete
    deleted = models.BooleanField(default=False)

    class Meta:
        db_table = "posthog_heatmapsaved"
        indexes = [
            models.Index(fields=["team", "url"]),
            models.Index(fields=["status"]),
            models.Index(fields=["deleted"]),
        ]
        constraints = []
        unique_together = ("team", "short_id")

    @property
    def has_content(self) -> bool:
        return self.snapshots.filter(
            models.Q(content__isnull=False) | models.Q(content_location__isnull=False)
        ).exists()

    def get_analytics_metadata(self) -> dict:
        return {
            "team_id": self.team_id,
            "url": self.url,
            "data_url": self.data_url,
            "target_widths": self.target_widths,
            "type": self.type,
            "status": self.status,
        }


class HeatmapSnapshot(UUIDModel):
    heatmap = models.ForeignKey(SavedHeatmap, on_delete=models.CASCADE, related_name="snapshots")
    width = models.IntegerField()
    # Content storage (similar to ExportedAsset)
    content = models.BinaryField(null=True)
    content_location = models.TextField(null=True, blank=True, max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("heatmap", "width")
        indexes = [
            models.Index(fields=["heatmap", "width"]),
        ]
