from django.db import models
import re
from django.core.exceptions import ValidationError

from posthog.models.utils import UUIDModel, CreatedMetaFields, UpdatedMetaFields


def validate_folder_name(value):
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", value):
        raise ValidationError(
            f"{value} is not a valid folder name. Folder names can only contain letters, numbers or '_' ",
            params={"value": value},
        )


class DataWarehouseFolder(UUIDModel, CreatedMetaFields, UpdatedMetaFields):
    name = models.CharField(max_length=255, validators=[validate_folder_name])
    items = models.JSONField(default=list)
    parent = models.ForeignKey("self", on_delete=models.CASCADE, null=True, blank=True, related_name="children")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="warehouse_folders")

    class Meta:
        unique_together = ("team", "name", "parent")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
