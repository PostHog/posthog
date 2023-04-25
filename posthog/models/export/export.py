import datetime as dt
from dataclasses import asdict
from typing import Optional
from uuid import UUID

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleIntervalSpec,
    ScheduleSpec,
    ScheduleState,
)

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

        self.create_temporal_schedule(schedule)

        return schedule

    def create_temporal_schedule(self, export_schedule: "ExportSchedule"):
        """Create an Schedule in Temporal matching ExportSchedule model."""
        from posthog.temporal.client import sync_connect
        from posthog.temporal.workflows import DESTINATION_WORKFLOWS

        destination = export_schedule.destination
        workflow, workflow_inputs = DESTINATION_WORKFLOWS[destination.type]
        schedule_spec = export_schedule.get_schedule_spec()

        common_search_attributes = {
            "DestinationId": [str(destination.id)],
            "DestinationType": [destination.type],
            "TeamId": [export_schedule.team.id],
            "TeamName": [export_schedule.team.name],
        }

        client = sync_connect()
        async_to_sync(client.create_schedule)(
            id=str(export_schedule.id),
            schedule=Schedule(
                action=ScheduleActionStartWorkflow(
                    workflow.run,
                    workflow_inputs(team_id=export_schedule.team.id, **destination.config),
                    id=f"{export_schedule.team.id}-{destination.type}-export",
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    search_attributes=common_search_attributes | {"ScheduleId": [str(export_schedule.id)]},
                ),
                spec=schedule_spec,
                state=ScheduleState(
                    note=f"Schedule created for destination {destination.id} in team {export_schedule.team.id}."
                ),
            ),
            search_attributes=common_search_attributes,
        )

    def get_export_schedule_from_name(self, name: str | None) -> Optional["ExportSchedule"]:
        if not name:
            return None
        try:
            return ExportSchedule.objects.get(name=name)
        except ExportSchedule.DoesNotExist:
            return None


class ExportSchedule(UUIDModel):
    """The Schedule an Export will follow.

    An ExportSchedule provides a model representation of a Temporal Schedule we can serve via our API.
    In Temporal, a Schedule is just another Workflow that executes an Action as indicated by its spec.
    This Action is usually triggering another Workflow. Our ExportSchedules are Temporal Schedules that
    specifically trigger Export Workflows. As such, an ExportSchedule has an associated destination.
    """

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
    """ExportRun model manager."""

    def create(
        self,
        team_id: int,
        destination_id: str,
        schedule_id: str | None,
        data_interval_start: str,
        data_interval_end: str,
    ) -> "ExportRun":
        """Create an ExportRun.

        In a first approach, this method is intended to be called only by Temporal Workflows,
        as only the Workflows themselves can know when they start.

        Args:
            team_id: The Team's id this ExportRun belongs to.
            destination_id: The destination targetted by this ExportRun.
            schedule_id: If triggered by a Schedule, the Schedule's id, otherwise None.
            data_interval_start:
            data_interval_end:
        """
        if schedule_id:
            schedule = ExportSchedule.objects.filter(id=schedule_id).first()
        else:
            schedule = None

        team = Team.objects.filter(id=team_id).first()
        destination = ExportDestination.objects.filter(id=destination_id).first()

        run = ExportRun(
            destination=destination,
            schedule=schedule,
            team=team,
            status=ExportRun.Status.STARTING,
            data_interval_start=dt.datetime.fromisoformat(data_interval_start),
            data_interval_end=dt.datetime.fromisoformat(data_interval_end),
        )
        run.save()

        return run

    def update_status(self, export_run_id: UUID, status: str):
        """Update the status of an ExportRun with given id."""
        run = ExportRun.objects.filter(id=export_run_id).first()
        if not run:
            raise ValueError(f"ExportRun with id {export_run_id} not found.")

        run.status = status
        run.save()


class ExportRun(UUIDModel):
    """Model to represent an instance of an Export.

    The state of this instance is populated by all necessary parameters to execute an export.
    """

    class Status(models.TextChoices):
        """All possible Workflow statuses as described by Temporal.

        See: https://docs.temporal.io/workflows#status.
        """

        CANCELLED = "Cancelled"
        COMPLETED = "Completed"
        CONTINUEDASNEW = "ContinuedAsNew"
        FAILED = "Failed"
        TERMINATED = "Terminated"
        TIMEDOUT = "TimedOut"
        RUNNING = "Running"
        STARTING = "Starting"

    objects: ExportRunManager = ExportRunManager()

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    destination: models.ForeignKey = models.ForeignKey("ExportDestination", on_delete=models.CASCADE)
    schedule: models.ForeignKey = models.ForeignKey("ExportSchedule", on_delete=models.SET_NULL, null=True)
    run_id: models.TextField = models.TextField()
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
