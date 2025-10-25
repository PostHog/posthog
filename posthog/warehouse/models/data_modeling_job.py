from django.db import models
from django.utils import timezone

from posthog.models.utils import CreatedMetaFields, UpdatedMetaFields, UUIDTModel


class DataModelingJob(CreatedMetaFields, UpdatedMetaFields, UUIDTModel):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        COMPLETED = "Completed", "Completed"
        FAILED = "Failed", "Failed"
        CANCELLED = "Cancelled", "Cancelled"

    team = models.ForeignKey("posthog.Team", on_delete=models.SET_NULL, null=True)
    saved_query = models.ForeignKey("posthog.DataWarehouseSavedQuery", on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=400, choices=Status.choices, default=Status.RUNNING)
    rows_materialized = models.IntegerField(default=0)
    error = models.TextField(null=True, blank=True)
    workflow_id = models.CharField(max_length=400, null=True, blank=True)
    workflow_run_id = models.CharField(max_length=400, null=True, blank=True)
    last_run_at = models.DateTimeField(default=timezone.now)
    rows_expected = models.IntegerField(null=True, blank=True, help_text="Total rows expected to be materialized")
    storage_delta_mib = models.FloatField(null=True, blank=True, default=0)
