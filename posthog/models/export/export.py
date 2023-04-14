from typing import Type, Any

from django.db import models
from temporalio.client import ScheduleSpec

from posthog.models.utils import UUIDModel
from posthog.models.team import Team
from posthog.temporal.workflows import S3ExportWorkflow, S3ExportInputs
from posthog.temporal.workflows.base import PostHogWorkflow


class ExportDestination(UUIDModel):
    """A destination for an Export."""

    class Destination(models.TextChoices):
        """Enumeration of supported destinations."""

        S3 = "S3"

    destinations_to_workflows = {
        Destination.S3: (S3ExportWorkflow, S3ExportInputs),
    }
    type: models.CharField = models.CharField(choices=Destination.choices)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    parameters: models.JSONField = models.JSONField(default=dict, blank=True)

    def get_temporal_workflow(self) -> tuple[Type[PostHogWorkflow], Any]:
        return self.destinations_to_workflows[self.destination_name]


class ExportScheduleManager(models.Manager):
    def create(
        self,
        team: Team,
        name: str,
        destination_type: str | None = None,
        destination_parameters: dict | None = None,
        destination_name: str | None = None,
    ) -> "ExportSchedule":
        if not destination_name:
            destination = ExportDestination(
                type=destination_type,
                team=team,
                parameters=destination_parameters,
            )
            destination.save()
        else:
            destination = ExportDestination.objects.filter(name=destination_name)

        schedule = ExportSchedule(
            team=team,
            name=name,
            destination=destination,
        )
        schedule.save()

        return schedule

    def get_export_schedule_from_name(self, name: str | None) -> "ExportSchedule" | None:
        if not name:
            return None
        try:
            return ExportSchedule.objects.get(name=name)
        except ExportSchedule.DoesNotExist:
            return None


class ExportSchedule(UUIDModel):
    """The Schedule an Export will follow."""

    objects: ExportScheduleManager = ExportScheduleManager()
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    paused_at: models.DateTimeField = models.DateTimeField(null=True)
    unpaused_at: models.DateTimeField = models.DateTimeField(null=True)
    start_at: models.DateTimeField = models.DateTimeField(null=True)
    end_at: models.DateTimeField = models.DateTimeField(null=True)
    name: models.CharField = models.CharField()
    destination: models.ForeignKey = models.ForeignKey("ExportDestination", on_delete=models.CASCADE)
    spec: models.JSONField = models.JSONField()

    def get_schedule_spec(self) -> ScheduleSpec:
        """Return a Temporal ScheduleSpec as specified by self.spec."""
        return ScheduleSpec()  # TODO


class ExportRun(UUIDModel):
    """Model to represent an instance of an Export."""

    class Status(models.TextChoices):
        """All possible Workflow statuses as described by Temporal.

        See: https://docs.temporal.io/workflows#status.
        """

        RUNNING = "Running"
        CANCELLED = "Cancelled"
        COMPLETED = "Completed"
        CONTINUEDASNEW = "ContinuedAsNew"
        FAILED = "Failed"
        TERMINATED = "Terminated"
        TIMEDOUT = "TimedOut"

    workflow: models.ForeignKey = models.ForeignKey("Workflow", on_delete=models.CASCADE)
    status: models.CharField = models.CharField(choices=Status.choices)
    opened_at: models.DateTimeField = models.DateTimeField(null=True)
    closed_at: models.DateTimeField = models.DateTimeField(null=True)

    def is_open(self) -> bool:
        """Check whether this Workflow is currently open."""
        return self.status == self.Status.RUNNING

    def is_closed(self) -> bool:
        """Check whether this Workflow is currently closed."""
        return self.status != self.Status.RUNNING
