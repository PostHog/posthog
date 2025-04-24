from django.db import models
from posthog.warehouse.models.datawarehouse_saved_query import DataWarehouseSavedQuery
from posthog.warehouse.models.version_control.version import Version


class DataWarehouseSavedQueryVersion(models.Model):
    saved_query = models.ForeignKey(DataWarehouseSavedQuery, on_delete=models.CASCADE)
    version = models.ForeignKey(Version, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
