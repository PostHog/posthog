from django.db import models

from posthog.models.team import Team
from posthog.models.utils import CreatedMetaFields, DeletedMetaFields, UpdatedMetaFields, UUIDTModel


class DataWarehouseSnapshotJob(CreatedMetaFields, UpdatedMetaFields, UUIDTModel, DeletedMetaFields):
    class Status(models.TextChoices):
        RUNNING = "Running", "Running"
        COMPLETED = "Completed", "Completed"
        FAILED = "Failed", "Failed"

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    config = models.ForeignKey("posthog.DataWarehouseSnapshotConfig", on_delete=models.CASCADE)

    # Each snapshot job will create a saved query that is filtered to the state of the table at run time
    table = models.ForeignKey("posthog.DataWarehouseSavedQuery", on_delete=models.CASCADE, null=True, blank=True)
    status = models.CharField(max_length=400, choices=Status.choices, default=Status.RUNNING)
    error = models.TextField(null=True, blank=True)
    workflow_id = models.CharField(max_length=400, null=True, blank=True)
    workflow_run_id = models.CharField(max_length=400, null=True, blank=True)
