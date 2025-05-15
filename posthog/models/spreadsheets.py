from django.db import models
from posthog.models.utils import UUIDModel, CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields


class Spreadsheet(UUIDModel, CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields):
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    data = models.JSONField(default=list)
    formatting = models.JSONField(default=list)
    settings = models.JSONField(default=dict)
    data_updated_at = models.DateTimeField()
    short_id = models.CharField(max_length=32)
