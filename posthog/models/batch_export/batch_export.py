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


class BatchExportDestination(UUIDModel):
    """A destination for a BatchExport."""

    class Destination(models.TextChoices):
        """Enumeration of supported destinations."""

        S3 = "S3"

    name: models.TextField = models.TextField()
    type: models.CharField = models.CharField(choices=Destination.choices, max_length=64)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    config: models.JSONField = models.JSONField(default=dict, blank=True)


class BatchExportScheduleManager(models.Manager):
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
        destination: BatchExportDestination | None = None,
    ) -> "BatchExportSchedule":
        schedule = BatchExportSchedule(
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

    def create_temporal_schedule(self, export_schedule: "BatchExportSchedule"):
        """Create an Schedule in Temporal matching BatchExportSchedule model."""
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
                    workflow_inputs(
                        team_id=export_schedule.team.id, destination_id=destination.id, **destination.config
                    ),
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

    def get_export_schedule_from_name(self, name: str | None) -> Optional["BatchExportSchedule"]:
        if not name:
            return None
        try:
            return BatchExportSchedule.objects.get(name=name)
        except BatchExportSchedule.DoesNotExist:
            return None


class BatchExportSchedule(UUIDModel):
    """The Schedule a BatchExport will follow.

    An BatchExportSchedule provides a model representation of a Temporal Schedule we can serve via our API.
    In Temporal, a Schedule is just another Workflow that executes an Action as indicated by its spec.
    This Action is usually triggering another Workflow. Our BatchExportSchedules are Temporal Schedules that
    specifically trigger BatchExport Workflows. As such, a BatchExportSchedule has an associated destination.
    """

    objects: BatchExportScheduleManager = BatchExportScheduleManager()

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    paused_at: models.DateTimeField = models.DateTimeField(null=True)
    unpaused_at: models.DateTimeField = models.DateTimeField(null=True)
    start_at: models.DateTimeField = models.DateTimeField(null=True)
    end_at: models.DateTimeField = models.DateTimeField(null=True)
    name: models.CharField = models.CharField(max_length=256)
    destination: models.ForeignKey = models.ForeignKey(
        "BatchExportDestination", on_delete=models.CASCADE, related_name="schedules"
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


class BatchExportRunManager(models.Manager):
    """BatchExportRun model manager."""

    def create(
        self,
        team_id: int,
        destination_id: UUID,
        schedule_id: UUID | None,
        data_interval_start: str,
        data_interval_end: str,
    ) -> "BatchExportRun":
        """Create an BatchExportRun.

        In a first approach, this method is intended to be called only by Temporal Workflows,
        as only the Workflows themselves can know when they start.

        Args:
            team_id: The Team's id this BatchExportRun belongs to.
            destination_id: The destination targetted by this BatchExportRun.
            schedule_id: If triggered by a Schedule, the Schedule's id, otherwise None.
            data_interval_start:
            data_interval_end:
        """
        if schedule_id:
            schedule = BatchExportSchedule.objects.filter(id=schedule_id).first()
        else:
            schedule = None

        team = Team.objects.filter(id=team_id).first()
        destination = BatchExportDestination.objects.filter(id=destination_id).first()

        run = BatchExportRun(
            destination=destination,
            schedule=schedule,
            team=team,
            status=BatchExportRun.Status.STARTING,
            data_interval_start=dt.datetime.fromisoformat(data_interval_start),
            data_interval_end=dt.datetime.fromisoformat(data_interval_end),
        )
        run.save()

        return run

    def update_status(self, export_run_id: UUID, status: str):
        """Update the status of an BatchExportRun with given id."""
        run = BatchExportRun.objects.filter(id=export_run_id).first()
        if not run:
            raise ValueError(f"BatchExportRun with id {export_run_id} not found.")

        run.status = status
        run.save()


class BatchExportRun(UUIDModel):
    """Model to represent an instance of an BatchExport.

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

    objects: BatchExportRunManager = BatchExportRunManager()

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    destination: models.ForeignKey = models.ForeignKey("BatchExportDestination", on_delete=models.CASCADE)
    schedule: models.ForeignKey = models.ForeignKey("BatchExportSchedule", on_delete=models.SET_NULL, null=True)
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
