from django.db import models
from django.utils import timezone

from posthog.models.utils import UUIDModel, CreatedMetaFields, DeletedMetaFields


class DataWarehouseFolder(UUIDModel, CreatedMetaFields, DeletedMetaFields):
    name = models.CharField(max_length=255)
    items = models.JSONField(default=list)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="warehouse_folders")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("team", "name", "parent")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
