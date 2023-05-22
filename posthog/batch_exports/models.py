from django.db import models

from posthog.models.utils import UUIDModel


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
    type: models.CharField = models.CharField(choices=Destination.choices, max_length=64)
    config: models.JSONField = models.JSONField(default=dict, blank=True)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)


class BatchExportRun(UUIDModel):
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

    batch_export = models.ForeignKey("BatchExport", on_delete=models.CASCADE)
    workflow_id: models.TextField = models.TextField()
    run_id: models.TextField = models.TextField()
    status: models.CharField = models.CharField(choices=Status.choices, max_length=64)
    opened_at: models.DateTimeField = models.DateTimeField(null=True)
    closed_at: models.DateTimeField = models.DateTimeField(null=True)
    data_interval_start: models.DateTimeField = models.DateTimeField()
    data_interval_end: models.DateTimeField = models.DateTimeField()
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)


class BatchExport(UUIDModel):
    """A model for PostHog BatchExports running on Temporal.

    A BatchExport is defined by an association between a destination and a schedule:
    - BatchExportDestination: where are we exporting data?
    - BatchExportSchedule: when and which data are we exporting?

    Temporal doesn't have a notion of a BatchExport: Our models are an abstraction on top of Temporal to support
    a REST API for managing Workflows, and expose and store execution metrics. As such, the biggest challenge with
    BatchExports is ensuring the state of these models is kept up-to-date with the underlying Temporal data.
    """

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    name: models.TextField = models.TextField()
    destination: models.ForeignKey = models.ForeignKey("BatchExportDestination", on_delete=models.CASCADE)
    interval = models.CharField(
        max_length=64, null=False, choices=[("hour", "hour"), ("day", "day"), ("week", "week")], default="hour"
    )
    paused = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True)
    last_updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)
