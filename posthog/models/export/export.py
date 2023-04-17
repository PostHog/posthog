import datetime as dt
from dataclasses import asdict
from typing import Any, Type

from django.contrib.postgres.fields import ArrayField
from django.db import models
from temporalio.client import ScheduleCalendarSpec, ScheduleIntervalSpec, ScheduleSpec

from posthog.models.team import Team
from posthog.models.utils import UUIDModel
from posthog.temporal.workflows import S3ExportInputs, S3ExportWorkflow
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
        return self.destinations_to_workflows[self.type]


class ExportScheduleManager(models.Manager):
    def create(
        self,
        team: Team,
        name: str,
        calendars: list[ScheduleCalendarSpec] | None = None,
        intervals: list[ScheduleIntervalSpec] | None = None,
        cron_expressions: list[str] | None = None,
        skip: list[ScheduleCalendarSpec] | None = None,
        start_at: dt.datetime | None = None,
        end_at: dt.datetime | None = None,
        jitter: dt.timedelta | None = None,
        destination_type: str | None = None,
        destination_parameters: dict | None = None,
        destination_name: str | None = None,
        time_zone_name: str = "Etc/UTC",
    ) -> "ExportSchedule":
        if not destination_name:
            destination = ExportDestination(
                type=destination_type,
                team=team,
                parameters=destination_parameters,
            )
            destination.save()
        else:
            destination = ExportDestination.objects.filter(type=destination_type)

        schedule = ExportSchedule(
            team=team,
            name=name,
            destination=destination,
            calendars=[asdict(calendar) for calendar in calendars or []],
            intervals=[asdict(interval) for interval in intervals or []],
            cron_expressions=cron_expressions,
            skip=[asdict(s) for s in skip or []],
            start_at=start_at,
            end_at=end_at,
            jitter=jitter,
            time_zone_name=time_zone_name,
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
    calendars: ArrayField = ArrayField(models.JSONField(), default=list)
    intervals: ArrayField = ArrayField(models.JSONField(), default=list)
    cron_expressions: ArrayField = ArrayField(models.CharField(), default=list)
    skip: ArrayField = ArrayField(models.JSONField(), default=list)
    jitter: models.DurationField = models.DurationField(null=True)
    time_zone_name: models.CharField = models.CharField(default="Etc/UTC", null=True)

    def get_schedule_spec(self) -> ScheduleSpec:
        """Return a Temporal ScheduleSpec."""
        return ScheduleSpec(
            calendars=[ScheduleCalendarSpec(**calendar) for calendar in self.calendars],
            intervals=[ScheduleIntervalSpec(**interval) for interval in self.intervals],
            cron_expressions=self.cron_expressions,
            skip=[ScheduleCalendarSpec(**s) for s in self.skip],
            start_at=self.start_at,
            end_at=self.end_at,
            jitter=self.jitter,
        )


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
