from django.db import models

from posthog.models.utils import UUIDModel


class BatchExportDestination(UUIDModel):
    """
    A model for the destination that a PostHog BatchExport will target.

    This model answers the question: where are we exporting data? It contains
    all the necessary information to interact with a specific destination. As we
    wish to support multiple destinations, this forces us to relax schema
    requirements for any configuration parameters, as different destinations
    will have different configuration parameters.
    """

    class Destination(models.TextChoices):
        """Enumeration of supported destinations for PostHog BatchExports."""

        S3 = "S3"
        SNOWFLAKE = "Snowflake"

    secret_fields = {
        "S3": {"aws_access_key_id", "aws_secret_access_key"},
        "Snowflake": set("password"),
    }

    type: models.CharField = models.CharField(
        choices=Destination.choices, max_length=64, help_text="A choice of supported BatchExportDestination types."
    )
    config: models.JSONField = models.JSONField(
        default=dict,
        blank=True,
        help_text="A JSON field to store all configuration parameters required to access a BatchExportDestination.",
    )
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, help_text="The timestamp at which this BatchExportDestination was created."
    )
    last_updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True, help_text="The timestamp at which this BatchExportDestination was last updated."
    )


class BatchExportRun(UUIDModel):
    """
    A model representing a single run of a PostHog BatchExport given a time
    interval. It is used to keep track of the status and progress of the export
    between the specified time interval, as well as communicating any errors
    that may have occurred during the process.
    """

    class Status(models.TextChoices):
        """Possible states of the BatchExportRun."""

        CANCELLED = "Cancelled"
        COMPLETED = "Completed"
        CONTINUEDASNEW = "ContinuedAsNew"
        FAILED = "Failed"
        TERMINATED = "Terminated"
        TIMEDOUT = "TimedOut"
        RUNNING = "Running"
        STARTING = "Starting"

    batch_export = models.ForeignKey(
        "BatchExport", on_delete=models.CASCADE, help_text="The BatchExport this run belongs to."
    )
    status: models.CharField = models.CharField(
        choices=Status.choices, max_length=64, help_text="The status of this run."
    )
    records_completed: models.IntegerField = models.IntegerField(
        null=True, help_text="The number of records that have been exported."
    )
    latest_error: models.TextField = models.TextField(
        null=True, help_text="The latest error that occurred during this run."
    )
    data_interval_start: models.DateTimeField = models.DateTimeField(help_text="The start of the data interval.")
    data_interval_end: models.DateTimeField = models.DateTimeField(help_text="The end of the data interval.")
    cursor: models.TextField = models.TextField(null=True, help_text="An opaque cursor that may be used to resume.")
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, help_text="The timestamp at which this BatchExportRun was created."
    )
    finished_at: models.DateTimeField = models.DateTimeField(
        null=True, help_text="The timestamp at which this BatchExportRun finished, successfully or not."
    )
    last_updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True, help_text="The timestamp at which this BatchExportRun was last updated."
    )
    bytes_completed: models.BigIntegerField = models.BigIntegerField(
        null=True, help_text="The amount of bytes that have been exported."
    )


class BatchExport(UUIDModel):
    """
    Defines the configuration of PostHog to export data to a destination,
    either on a schedule (via the interval parameter), or manually by a
    "backfill". Specific instances of a unit process of exporting data is called
    a BatchExportRun.
    """

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, help_text="The team this belongs to.")
    name: models.TextField = models.TextField(help_text="A human-readable name for this BatchExport.")
    destination: models.ForeignKey = models.ForeignKey(
        "BatchExportDestination", on_delete=models.CASCADE, help_text="The destination to export data to."
    )
    interval = models.CharField(
        max_length=64,
        null=False,
        choices=[("hour", "hour"), ("day", "day"), ("week", "week")],
        default="hour",
        help_text="The interval at which to export data.",
    )
    paused = models.BooleanField(default=False, help_text="Whether this BatchExport is paused or not.")
    deleted = models.BooleanField(default=False, help_text="Whether this BatchExport is deleted or not.")
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, help_text="The timestamp at which this BatchExport was created."
    )
    last_updated_at: models.DateTimeField = models.DateTimeField(
        auto_now=True, help_text="The timestamp at which this BatchExport was last updated."
    )
    last_paused_at: models.DateTimeField = models.DateTimeField(
        null=True, default=None, help_text="The timestamp at which this BatchExport was last paused."
    )
    start_at: models.DateTimeField = models.DateTimeField(
        null=True, default=None, help_text="Time before which any Batch Export runs won't be triggered."
    )
    end_at: models.DateTimeField = models.DateTimeField(
        null=True, default=None, help_text="Time after which any Batch Export runs won't be triggered."
    )
