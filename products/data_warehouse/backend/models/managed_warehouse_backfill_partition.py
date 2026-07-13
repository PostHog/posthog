from django.db import models

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel


class ManagedWarehouseBackfillPartition(TeamScopedRootMixin, UUIDModel):
    class Dataset(models.TextChoices):
        EVENTS = "events", "Events"
        PERSONS = "persons", "Persons"

    class LifecycleState(models.TextChoices):
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    # team is the canonical tenant boundary; environment_id preserves the exact
    # project because sibling environments share a team scope.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    environment_id = models.BigIntegerField()
    dataset = models.CharField(max_length=16, choices=Dataset.choices)
    partition_key = models.CharField(max_length=128)
    lifecycle_state = models.CharField(max_length=16, choices=LifecycleState.choices)
    run_id = models.CharField(max_length=64)
    started_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=128, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "environment_id", "dataset", "partition_key"],
                name="unique_managed_warehouse_backfill_partition",
            )
        ]
