import dataclasses
import datetime as dt
from uuid import UUID

from asgiref.sync import async_to_sync
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleBackfill,
    ScheduleCalendarSpec,
    ScheduleDescription,
    ScheduleHandle,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    ScheduleRange,
    ScheduleSpec,
    ScheduleState,
    WorkflowExecutionDescription,
    WorkflowHandle,
)
from temporalio.common import RetryPolicy

from posthog.models.team import Team
from posthog.models.utils import UUIDModel


class TemporalModel(UUIDModel):
    """A model base class for models that need to interact with Temporal."""

    class Meta:
        abstract = True

    _temporal_client = None

    @property
    def temporal_client(self) -> Client:
        """Return a Temporal Client, initializing it if necessary."""
        from posthog.temporal.client import sync_connect

        if self._temporal_client is None:
            self._temporal_client = sync_connect()
        return self._temporal_client

    def create_schedule(self, id: str, schedule: Schedule, search_attributes: dict) -> ScheduleHandle:
        """Create a Temporal Schedule."""
        return async_to_sync(self.temporal_client.create_schedule)(
            id=id,
            schedule=schedule,
            search_attributes=search_attributes,
        )

    def get_schedule_handle(self, id: str) -> ScheduleHandle:
        """Return a Temporal Schedule's handle."""
        return self.temporal_client.get_schedule_handle(id)

    def backfill_schedule(self, id: str, backfill: ScheduleBackfill) -> None:
        """Trigger a backfill on a Temporal Schedule."""
        handle = self.get_schedule_handle(id)
        async_to_sync(handle.backfill)(backfill)

    def delete_schedule(self, id: str) -> None:
        """Delete a Temporal Schedule."""
        handle = self.get_schedule_handle(id)
        async_to_sync(handle.delete)()

    def pause_schedule(self, id: str, note: str | None = None) -> None:
        """Pause a Temporal Schedule."""
        handle = self.get_schedule_handle(id)
        async_to_sync(handle.pause)(note=note)

    def unpause_schedule(self, id: str, note: str | None = None) -> None:
        """Unpause a Temporal Schedule."""
        handle = self.get_schedule_handle(id)
        async_to_sync(handle.unpause)(note=note)

    def describe_schedule(self, id: str) -> ScheduleDescription:
        """Describe a Temporal Schedule."""
        handle = self.get_schedule_handle(id)
        return async_to_sync(handle.describe)()

    def trigger_schedule(
        self, id: str, overlap: ScheduleOverlapPolicy = ScheduleOverlapPolicy.ALLOW_ALL
    ) -> ScheduleDescription:
        """Trigger a Temporal Schedule."""
        handle = self.get_schedule_handle(id)
        return async_to_sync(handle.trigger)(overlap=overlap)

    def get_workflow_handle(self, id: str, run_id: str | None = None) -> WorkflowHandle:
        """Return a Temporal Workflow's handle."""
        return self.temporal_client.get_workflow_handle(workflow_id=id, run_id=run_id)

    def describe_workflow(self, id: str, run_id: str | None = None) -> WorkflowExecutionDescription:
        """Describe a Temporal Workflow in execution."""
        handle = self.get_workflow_handle(id, run_id)
        return async_to_sync(handle.describe)()

    def cancel_workflow(self, id: str, run_id: str | None = None) -> WorkflowExecutionDescription:
        """Cancel a Temporal Workflow in execution."""
        handle = self.get_workflow_handle(id, run_id)
        return async_to_sync(handle.cancel)()

    def terminate_workflow(
        self, id: str, run_id: str | None = None, reason: str | None = None
    ) -> WorkflowExecutionDescription:
        """Terminate a Temporal Workflow in execution.

        Termination doesn't kills the Workflow immediately, without time to execute any clean-up activities.
        """
        handle = self.get_workflow_handle(id, run_id)
        return async_to_sync(handle.terminate)(reason=reason)


class BatchExportDestination(UUIDModel):
    """A model for the destination that a PostHog BatchExport will target.

    This model answers the question: where are we exporting data? It contains all the necessary
    information to interact with a specific destination. As we wish to support multiple destinations,
    this forces us to relax schema requirements for any configuration parameters, as different
    destinations will have different configuration parameters.

    Temporal has no notion of destinations: this model is meant as an abstraction layer for users. As
    such, this model doesn't concern itself with how the data will be accessed by the Temporal Workflows
    executing BatchExports.

    Attributes:
        team: The Team this BatchExportDestination belongs to.
        name: A name given to this BatchExportDestination by the user.
        type: A choice of supported BatchExportDestination types. This information is later used to
            determine the actual Temporal Workflow to execute.
        config: A JSON field to store all configuration parameters required to access a
            BatchExportDestination.
        created_at:
        last_updated_at:
    """

    class Destination(models.TextChoices):
        """Enumeration of supported destinations for PostHog BatchExports.

        Each of these destinations should have an associated Temporal Workfl
        """

        S3 = "S3"

    secret_fields = {Destination.S3: {"aws_access_key_id", "aws_secret_access_key"}}

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    name: models.TextField = models.TextField()
    type: models.CharField = models.CharField(choices=Destination.choices, max_length=64)
    config: models.JSONField = models.JSONField(default=dict, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)


class BatchExportScheduleManager(models.Manager):
    def create(
        self,
        team: Team,
        paused: bool = False,
        calendars: list[dict] | None = None,
        intervals: list[dict] | None = None,
        cron_expressions: list[str] | None = None,
        skip: list[dict] | None = None,
        start_at: dt.datetime | None = None,
        end_at: dt.datetime | None = None,
        jitter: dt.timedelta | None = None,
        time_zone_name: str = "Etc/UTC",
    ) -> "BatchExportSchedule":
        start_at = start_at or dt.datetime.utcnow()
        schedule = BatchExportSchedule(
            team=team,
            paused=paused,
            calendars=calendars or [],
            intervals=intervals or [],
            cron_expressions=cron_expressions or [],
            skip=skip or [],
            start_at=start_at,
            end_at=end_at,
            jitter=jitter,
            time_zone_name=time_zone_name,
        )
        schedule.save()
        return schedule


def schedule_spec_from_dict(schedule_spec_class, d: dict):
    """Initialize a Schedule*Spec from a dictionary.

    This is used to convert the JSONField stored in a BatchExportSchedule model into a Schedule*Spec instance
    that can be passed to Temporal calls.
    """
    fields = {}
    for field in dataclasses.fields(schedule_spec_class):
        if field.name not in d:
            continue

        dict_value = d[field.name]
        if isinstance(dict_value, (list, tuple)):
            value = type(dict_value)(ScheduleRange(**value) for value in dict_value)
        elif isinstance(dict_value, dict) and field.name in ("offset", "every"):
            value = dt.timedelta(**dict_value)
        else:
            value = dict_value

        fields[field.name] = value

    return schedule_spec_class(**fields)


class BatchExportSchedule(TemporalModel):
    """A model for the schedule a PostHog BatchExport will follow.

    A BatchExportSchedule provides a model representation of a Temporal Schedule we can serve via the PostHog REST API.
    In Temporal, a Schedule is just another Workflow that executes an Action. In particular, our BatchExportSchedules are
    Temporal Schedules that trigger BatchExport Workflows as their Action.

    Schedules in Temporal are defined by their specification, of which we can distinguish three types:
    - Calendar: A calendar specifcation contains ranges of units; a timestamp matches if at least one
        range of each unit matches. For example, a calendar specification may be set to match all timestamps that fall
        in the hour ranges 1-3 and 10-12 and the day of week range 0-2. This means a Workflow will be triggered
        every Sunday, Monday, and Tuesday at every hour between 1 and 3 and between 10 and 12.
        This is perhaps the most powerful specification in terms of what you can express with it.
    - Interval: An interval specification contains a timedelta and an offset; matches timestamps in the series given by
        the formula epoch + (n * every) + offset. For example, setting every to the timedelta 1 hour and offset to 10
        minutes will execute a Workflow 10 minutes after evey hour mark.
    - Cron: A simple cron expression. This is not represented by a separate class in the Temporal SDK but
        by a simple str.

    A single Schedule can contain multiple specifications. Temporal will do a union on all of them.

    Attributes:
        team: The Team this BatchExportSchedule belongs to.
        created_at: When the BatchExportSchedule was created.
        last_updated_at: When the BatchExportSchedule was last updated.
        skip: A set of calendar specifications for which no BatchExport Workflow will be triggered.
    """

    objects: BatchExportScheduleManager = BatchExportScheduleManager()

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    paused_at: models.DateTimeField = models.DateTimeField(null=True)
    unpaused_at: models.DateTimeField = models.DateTimeField(null=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
    start_at: models.DateTimeField = models.DateTimeField()
    end_at: models.DateTimeField = models.DateTimeField(null=True)
    calendars: ArrayField = ArrayField(models.JSONField(), default=list, blank=True)
    intervals: ArrayField = ArrayField(models.JSONField(), default=list, blank=True)
    cron_expressions: ArrayField = ArrayField(models.TextField(), default=list, blank=True)
    skip: ArrayField = ArrayField(models.JSONField(), default=list)
    paused: models.BooleanField = models.BooleanField(default=False)
    jitter: models.DurationField = models.DurationField(null=True)
    time_zone_name: models.CharField = models.CharField(max_length=64, default="Etc/UTC", null=True)

    def get_schedule_spec(self) -> ScheduleSpec:
        """Return a Temporal ScheduleSpec.

        Essentially maps this instance's specification fields to Temporal's ScheduleSpec.

        Returns:
            A ScheduleSpec derived from this BatchExportSchedule.
        """
        return ScheduleSpec(
            calendars=[schedule_spec_from_dict(ScheduleCalendarSpec, calendar) for calendar in self.calendars],
            intervals=[schedule_spec_from_dict(ScheduleIntervalSpec, interval) for interval in self.intervals],
            cron_expressions=self.cron_expressions,
            skip=[schedule_spec_from_dict(ScheduleCalendarSpec, s) for s in self.skip],
            start_at=self.start_at,
            end_at=self.end_at,
            jitter=self.jitter,
        )

    def pause(self, note: str | None = None) -> "BatchExportSchedule":
        """Pause this BatchExportSchedule by calling Temporal.

        Arguments:
            note: A note to add in Temporal when pausing.
        """
        if self.paused is True:
            raise ValueError("Cannot pause Schedule that is already paused")

        self.pause_schedule(str(self.id), note)

        description = self.describe_schedule(str(self.id))
        self.paused = True
        self.paused_at = description.info.last_updated_at or dt.datetime.utcnow()
        self.last_updated_at = description.info.last_updated_at or dt.datetime.utcnow()
        self.save()

        return self

    def unpause(self, note: str | None = None) -> "BatchExportSchedule":
        """Unpause this BatchExportSchedule by calling Temporal.

        Arguments:
            note: A note to add in Temporal when unpausing.
        """
        if self.paused is False:
            raise ValueError("Cannot unpause Schedule that is not paused")

        self.unpause_schedule(str(self.id), note)

        description = self.describe_schedule(str(self.id))
        self.paused = False
        self.paused_at = description.info.last_updated_at or dt.datetime.utcnow()
        self.last_updated_at = description.info.last_updated_at or dt.datetime.utcnow()
        self.save()

        return self

    def backfill(self, start_at: dt.datetime | None = None, end_at: dt.datetime | None = None) -> "BatchExportSchedule":
        """Backfill this BatchExportSchedule by calling Temporal.

        Arguments:
            start_at: From when to backfill. If this is not defined, then we will backfill since this
                BatchExportSchedule's start_at.
            end_at: Up to when to backfill. If this is not defined, then we will backfill up to this
                BatchExportSchedule's created_at.
        """
        backfill_start_at = start_at or self.start_at
        backfill_end_at = end_at or self.created_at

        if backfill_end_at < backfill_start_at:
            raise ValueError("Backfill start_at cannot be after backfill end_at")

        backfill = ScheduleBackfill(
            start_at=backfill_start_at,
            end_at=backfill_end_at,
            overlap=ScheduleOverlapPolicy.ALLOW_ALL,
        )
        self.backfill_schedule(str(self.id), backfill=backfill)

        return self

    def trigger(self, note: str | None = None) -> "BatchExportSchedule":
        """Trigger this BatchExportSchedule by calling Temporal."""
        self.trigger_schedule(str(self.id))
        return self


class BatchExportRunManager(models.Manager):
    """BatchExportRun model manager."""

    def create(
        self,
        team_id: int,
        workflow_id: str,
        run_id: str,
        batch_export_id: UUID,
        data_interval_start: str,
        data_interval_end: str,
    ) -> "BatchExportRun":
        """Create a BatchExportRun after a Temporal Workflow execution.

        In a first approach, this method is intended to be called only by Temporal Workflows,
        as only the Workflows themselves can know when they start.

        Args:
            data_interval_start:
            data_interval_end:
        """
        team = Team.objects.get(id=team_id)
        batch_export = BatchExport.objects.get(id=batch_export_id)
        run = BatchExportRun(
            team=team,
            batch_export=batch_export,
            workflow_id=workflow_id,
            run_id=run_id,
            status=BatchExportRun.Status.STARTING,
            data_interval_start=dt.datetime.fromisoformat(data_interval_start),
            data_interval_end=dt.datetime.fromisoformat(data_interval_end),
        )
        run.save()

        return run

    def update_status(self, id: UUID, status: str):
        """Update the status of an BatchExportRun with given id.

        Arguments:
            id: The id of the BatchExportRun to update.
        """
        run = BatchExportRun.objects.filter(id=id).first()
        if not run:
            raise ValueError(f"BatchExportRun with id {id} not found.")

        run.status = status
        run.save()


class BatchExportRun(TemporalModel):
    """A model for individual runs of a PostHog BatchExport.

    A BatchExportRun can be understood as an instance of a BatchExport, and it matches a Workflow execution in Temporal.

    The number of BatchExportRuns associatd with a BatchExport will depend on its BatchExportSchedule: the higher the
    frequency dictated by a BatchExportSchedule, the more BatchExportRuns that will be created.

    This model is mostly intended for reporting purposes as Temporal should manage the state to ensure it stays in sync
    with each Workflow Execution.

    Attributes:
        batch_export: The BatchExport this run belongs to.
        run_id: The Workflow execution ID created by Temporal.
        status: The status of the Workflow. Mostly dictated by the supported Temporal statuses.
        opened_at:
        closed_at:
        data_interval_start:
        data_interval_end:
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
    batch_export = models.ForeignKey("BatchExport", on_delete=models.CASCADE)
    workflow_id: models.TextField = models.TextField()
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

    def describe_workflow(self) -> WorkflowExecutionDescription:
        return super().describe_workflow(self.workflow_id, self.run_id)

    def cancel(self) -> None:
        """Cancel the underyling Workflow Execution represented by this BatchExportRun."""
        self.cancel_workflow(self.workflow_id, self.run_id)

    def terminate(self, reason: str | None = None) -> None:
        """Terminate the underyling Workflow Execution represented by this BatchExportRun."""
        self.terminate_workflow(self.workflow_id, self.run_id, reason=reason)


class BatchExportManager(models.Manager):
    """BatchExportRun model manager."""

    def create(
        self,
        team: Team,
        destination: BatchExportDestination,
        schedule: BatchExportSchedule,
    ) -> "BatchExport":
        batch_export = BatchExport(
            team=team,
            destination=destination,
            schedule=schedule,
        )
        batch_export.save()
        batch_export.create_batch_export_schedule()

        return batch_export


class BatchExport(TemporalModel):
    """A model for PostHog BatchExports running on Temporal.

    A BatchExport is defined by an association between a destination and a schedule:
    - BatchExportDestination: where are we exporting data?
    - BatchExportSchedule: when and which data are we exporting?

    Temporal doesn't have a notion of a BatchExport: Our models are an abstraction on top of Temporal to support
    a REST API for managing Workflows, and expose and store execution metrics. As such, the biggest challenge with
    BatchExports is ensuring the state of these models is kept up-to-date with the underlying Temporal data.
    """

    objects: BatchExportManager = BatchExportManager()

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    destination: models.ForeignKey = models.ForeignKey("BatchExportDestination", on_delete=models.CASCADE)
    schedule: models.ForeignKey = models.ForeignKey("BatchExportSchedule", on_delete=models.CASCADE)
    retry_policy: models.JSONField = models.JSONField(default=dict, blank=True)
    execution_timeout: models.DurationField = models.DurationField(default=None, null=True, blank=True)
    run_timeout: models.DurationField = models.DurationField(default=None, null=True, blank=True)
    task_timeout: models.DurationField = models.DurationField(default=None, null=True, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)

    def create_batch_export_schedule(
        self,
    ) -> ScheduleHandle:
        """Create a Schedule in Temporal for this BatchExport.

        Returns:
            The ScheduleHandle for the created Temporal Schedule.
        """
        from posthog.temporal.workflows import DESTINATION_WORKFLOWS

        workflow, workflow_inputs = DESTINATION_WORKFLOWS[self.destination.type]
        schedule_spec = self.schedule.get_schedule_spec()

        # These attributes allow us to filter Workflows in Temporal.
        # Temporal adds TemporalScheduledById (the Schedule's id) and TemporalScheduledStartTime (the Action's timestamp).
        common_search_attributes = {
            "DestinationId": [str(self.destination.id)],
            "DestinationType": [self.destination.type],
            "TeamId": [self.schedule.team.id],
            "TeamName": [self.schedule.team.name],
            "BatchExportId": [str(self.id)],
        }

        state = ScheduleState(
            note=f"Schedule created for BatchExport {self.id} to Destination {self.destination.id} in Team {self.schedule.team.id}.",
            paused=self.schedule.paused,
        )

        handle = self.create_schedule(
            id=str(self.schedule.id),
            schedule=Schedule(
                action=ScheduleActionStartWorkflow(
                    workflow.run,
                    workflow_inputs(
                        team_id=self.schedule.team.id,
                        # We could take the batch_export_id from the Workflow id
                        # But temporal appends a timestamp at the end we would have to parse out.
                        batch_export_id=str(self.id),
                        **self.destination.config,
                    ),
                    id=str(self.id),
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                    search_attributes=common_search_attributes,
                    retry_policy=self.get_retry_policy(),
                    execution_timeout=self.execution_timeout,
                    task_timeout=self.task_timeout,
                    run_timeout=self.run_timeout,
                ),
                spec=schedule_spec,
                state=state,
            ),
            search_attributes=common_search_attributes,
        )

        return handle

    def get_retry_policy(self) -> RetryPolicy:
        """Return a Temporal RetryPolicy for this BatchExport."""
        policy_kwargs = self.retry_policy

        if "maximum_attempts" not in policy_kwargs:
            # By default, Temporal will retry indefinetely.
            # Unless explictly requested, let's cap this to a more reasonable 3 retries.
            policy_kwargs["maximum_attempts"] = 3

        policy = RetryPolicy(**policy_kwargs)
        # 100 * initial_interval is the default maximum_interval.
        # We set it here as Temporal initializes RetryPolicy with maximum_interval=None
        # even though that's not the default!
        policy.maximum_interval = self.retry_policy.get("maximum_interval", 100) * policy.initial_interval
        return policy

    def delete_batch_export_schedule(self):
        """Delete the Schedule in Temporal created for this BatchExport."""
        self.delete_schedule(id=str(self.schedule.id))

    def backfill(self, start_at: dt.datetime | None = None, end_at: dt.datetime | None = None) -> None:
        """Backfill this BatchExport.

        We pass the call to the underlying BatchExportSchedule. This exists here as a convinience so that users only
        need to interact with a BatchExport.
        """
        self.schedule.backfill(start_at, end_at)

    def trigger(self, note: str | None = None) -> None:
        """Trigger this BatchExport.

        We pass the call to the underlying BatchExportSchedule. This exists here as a convinience so that users only
        need to interact with a BatchExport.
        """
        self.schedule.trigger(note)

    def pause(self, note: str | None = None) -> None:
        """Pause this BatchExport.

        We pass the call to the underlying BatchExportSchedule. This exists here as a convinience so that users only
        need to interact with a BatchExport.
        """
        self.schedule.pause(note=note)

    def unpause(self, note: str | None = None) -> None:
        """Unpause this BatchExport.

        We pass the call to the underlying BatchExportSchedule. This exists here as a convinience so that users only
        need to interact with a BatchExport.
        """
        self.schedule.unpause(note=note)
