from posthog.models.utils import UUIDModel, CreatedMetaFields
from django.db import models
from .cluster import WarehouseCluster


class WarehouseNode(UUIDModel, CreatedMetaFields):
    host: models.CharField = models.CharField(max_length=500)
    port: models.IntegerField = models.IntegerField(default=8234)
    database: models.CharField = models.CharField(max_length=500, default="default")
    cluster: models.ForeignKey = models.ForeignKey(WarehouseCluster, on_delete=models.CASCADE)
    is_read_only: models.BooleanField = models.BooleanField(default=False)
