import datetime as dt
from dataclasses import asdict
from typing import Optional

from django.contrib.postgres.fields import ArrayField
from django.db import models
from temporalio.client import ScheduleCalendarSpec, ScheduleIntervalSpec, ScheduleSpec

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class ExportDestination(UUIDModel):
    """A destination for an Export."""

    class Destination(models.TextChoices):
        """Enumeration of supported destinations."""

        S3 = "S3"

    name: models.TextField = models.TextField()
    type: models.CharField = models.CharField(choices=Destination.choices, max_length=64)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    config: models.JSONField = models.JSONField(default=dict, blank=True)


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
        time_zone_name: str = "Etc/UTC",
        destination: ExportDestination | None = None,
    ) -> "ExportSchedule":
        schedule = ExportSchedule(
            team=team,
            name=name,
            destination=destination,
            calendars=[asdict(calendar) for calendar in calendars or []],
            intervals=[asdict(interval) for interval in intervals or []],
            cron_expressions=cron_expressions or [],
            skip=[asdict(s) for s in skip or []],
            start_at=start_at,
            end_at=end_at,
            jitter=jitter,
            time_zone_name=time_zone_name,
        )
        schedule.save()

        return schedule

    def get_export_schedule_from_name(self, name: str | None) -> Optional["ExportSchedule"]:
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
    name: models.CharField = models.CharField(max_length=256)
    destination: models.ForeignKey = models.ForeignKey(
        "ExportDestination", on_delete=models.CASCADE, related_name="schedules"
    )
    calendars: ArrayField = ArrayField(models.JSONField(), default=list, blank=True)
    intervals: ArrayField = ArrayField(models.JSONField(), default=list, blank=True)
    cron_expressions: ArrayField = ArrayField(models.TextField(), default=list, blank=True)
    skip: ArrayField = ArrayField(models.JSONField(), default=list)
    jitter: models.DurationField = models.DurationField(null=True)
    time_zone_name: models.CharField = models.CharField(max_length=64, default="Etc/UTC", null=True)

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


class ExportRunManager(models.Manager):
    def create(self, team_id: int, schedule_name: str, data_interval_start: str, data_interval_end: str) -> "ExportRun":
        schedule = ExportSchedule.objects.filter(team__pk=team_id, name=schedule_name)[0]
        run = ExportRun(
            schedule=schedule,
            status=ExportRun.Status.RUNNING,
            data_interval_start=dt.datetime.fromisoformat(data_interval_start),
            data_interval_end=dt.datetime.fromisoformat(data_interval_end),
        )
        run.save()

        return run

    def update_status(self, run_id: str, status: str):
        runs = ExportRun.objects.filter(run_id=run_id)
        if not runs.exists():
            raise ValueError(f"ExportRun with id {run_id} not found.")

        run = runs[0]
        run.status = status
        run.save()


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

    objects: ExportRunManager = ExportRunManager()

    schedule: models.ForeignKey = models.ForeignKey("ExportSchedule", on_delete=models.CASCADE)
    status: models.CharField = models.CharField(choices=Status.choices, max_length=64)
    opened_at: models.DateTimeField = models.DateTimeField(null=True)
    closed_at: models.DateTimeField = models.DateTimeField(null=True)
    data_interval_start: models.DateTimeField = models.DateTimeField()
    data_interval_end: models.DateTimeField = models.DateTimeField()

    def is_open(self) -> bool:
        """Check whether this Workflow is currently open."""
        return self.status == self.Status.RUNNING

    def is_closed(self) -> bool:
        """Check whether this Workflow is currently closed."""
        return self.status != self.Status.RUNNING
