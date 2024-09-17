import collections.abc
import datetime as dt
from datetime import timedelta

from django.db import models

from posthog.client import sync_execute
from posthog.models.utils import UUIDModel


class BatchExportDestination(UUIDModel):
    """A model for the destination that a PostHog BatchExport will target.

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
        POSTGRES = "Postgres"
        REDSHIFT = "Redshift"
        BIGQUERY = "BigQuery"
        HTTP = "HTTP"
        NOOP = "NoOp"

    secret_fields = {
        "S3": {"aws_access_key_id", "aws_secret_access_key"},
        "Snowflake": {"user", "password"},
        "Postgres": {"user", "password"},
        "Redshift": {"user", "password"},
        "BigQuery": {"private_key", "private_key_id", "client_email", "token_uri"},
        "HTTP": set("token"),
        "NoOp": set(),
    }

    type = models.CharField(
        choices=Destination.choices,
        max_length=64,
        help_text="A choice of supported BatchExportDestination types.",
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="A JSON field to store all configuration parameters required to access a BatchExportDestination.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The timestamp at which this BatchExportDestination was created.",
    )
    last_updated_at = models.DateTimeField(
        auto_now=True,
        help_text="The timestamp at which this BatchExportDestination was last updated.",
    )


class BatchExportRun(UUIDModel):
    """A model of a single run of a PostHog BatchExport given a time interval.

    It is used to keep track of the status and progress of the export
    between the specified time interval, as well as communicating any errors
    that may have occurred during the process.
    """

    class Status(models.TextChoices):
        """Possible states of the BatchExportRun."""

        CANCELLED = "Cancelled"
        COMPLETED = "Completed"
        CONTINUED_AS_NEW = "ContinuedAsNew"
        FAILED = "Failed"
        FAILED_RETRYABLE = "FailedRetryable"
        TERMINATED = "Terminated"
        TIMEDOUT = "TimedOut"
        RUNNING = "Running"
        STARTING = "Starting"

    batch_export = models.ForeignKey(
        "BatchExport",
        on_delete=models.CASCADE,
        help_text="The BatchExport this run belongs to.",
    )
    status = models.CharField(choices=Status.choices, max_length=64, help_text="The status of this run.")
    records_completed = models.IntegerField(null=True, help_text="The number of records that have been exported.")
    latest_error = models.TextField(null=True, help_text="The latest error that occurred during this run.")
    data_interval_start = models.DateTimeField(help_text="The start of the data interval.")
    data_interval_end = models.DateTimeField(help_text="The end of the data interval.")
    cursor = models.TextField(null=True, help_text="An opaque cursor that may be used to resume.")
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The timestamp at which this BatchExportRun was created.",
    )
    finished_at = models.DateTimeField(
        null=True,
        help_text="The timestamp at which this BatchExportRun finished, successfully or not.",
    )
    last_updated_at = models.DateTimeField(
        auto_now=True,
        help_text="The timestamp at which this BatchExportRun was last updated.",
    )
    records_total_count = models.IntegerField(
        null=True, help_text="The total count of records that should be exported in this BatchExportRun."
    )
    inserted_at_interval_start = models.DateTimeField(
        null=True,
        help_text="The inserted_at of the first record that was inserted into the destination in this BatchExportRun.",
    )
    inserted_at_interval_end = models.DateTimeField(
        null=True,
        help_text="The inserted_at of the last record that was inserted into the destination in this BatchExportRun.",
    )


def fetch_batch_export_run_count(
    *,
    team_id: int,
    data_interval_start: dt.datetime,
    data_interval_end: dt.datetime,
    exclude_events: collections.abc.Iterable[str] | None = None,
    include_events: collections.abc.Iterable[str] | None = None,
) -> int:
    """Fetch a list of batch export log entries from ClickHouse."""
    if exclude_events:
        exclude_events_statement = f"AND event NOT IN ({','.join(exclude_events)})"
    else:
        exclude_events_statement = ""

    if include_events:
        include_events_statement = f"AND event IN ({','.join(include_events)})"
    else:
        include_events_statement = ""

    data_interval_start_ch = data_interval_start.strftime("%Y-%m-%d %H:%M:%S")
    data_interval_end_ch = data_interval_end.strftime("%Y-%m-%d %H:%M:%S")

    clickhouse_query = f"""
        SELECT count(*)
        FROM events
        WHERE
            team_id = {team_id}
            AND timestamp >= toDateTime64('{data_interval_start_ch}', 6, 'UTC')
            AND timestamp < toDateTime64('{data_interval_end_ch}', 6, 'UTC')
            {exclude_events_statement}
            {include_events_statement}
    """

    try:
        return sync_execute(clickhouse_query)[0][0]
    except Exception:
        return 0


BATCH_EXPORT_INTERVALS = [
    ("hour", "hour"),
    ("day", "day"),
    ("week", "week"),
    ("every 5 minutes", "every 5 minutes"),
]


class BatchExport(UUIDModel):
    """
    Defines the configuration of PostHog to export data to a destination,
    either on a schedule (via the interval parameter), or manually by a
    "backfill". Specific instances of a unit process of exporting data is called
    a BatchExportRun.
    """

    class Model(models.TextChoices):
        """Possible models that this BatchExport can export."""

        EVENTS = "events"
        PERSONS = "persons"

    team = models.ForeignKey("Team", on_delete=models.CASCADE, help_text="The team this belongs to.")
    name = models.TextField(help_text="A human-readable name for this BatchExport.")
    destination = models.ForeignKey(
        "BatchExportDestination",
        on_delete=models.CASCADE,
        help_text="The destination to export data to.",
    )
    interval = models.CharField(
        max_length=64,
        null=False,
        choices=BATCH_EXPORT_INTERVALS,
        default="hour",
        help_text="The interval at which to export data.",
    )
    paused = models.BooleanField(default=False, help_text="Whether this BatchExport is paused or not.")
    deleted = models.BooleanField(default=False, help_text="Whether this BatchExport is deleted or not.")
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The timestamp at which this BatchExport was created.",
    )
    last_updated_at = models.DateTimeField(
        auto_now=True,
        help_text="The timestamp at which this BatchExport was last updated.",
    )
    last_paused_at = models.DateTimeField(
        null=True,
        default=None,
        help_text="The timestamp at which this BatchExport was last paused.",
    )
    start_at = models.DateTimeField(
        null=True,
        default=None,
        help_text="Time before which any Batch Export runs won't be triggered.",
    )
    end_at = models.DateTimeField(
        null=True,
        default=None,
        help_text="Time after which any Batch Export runs won't be triggered.",
    )

    schema = models.JSONField(
        null=True,
        default=None,
        help_text="A schema of custom fields to select when exporting data.",
    )

    model = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        choices=Model.choices,
        default=Model.EVENTS,
        help_text="Which model this BatchExport is exporting.",
    )

    @property
    def latest_runs(self):
        """Return the latest 10 runs for this batch export."""
        return self.batchexportrun_set.all().order_by("-created_at")[:10]

    @property
    def interval_time_delta(self) -> timedelta:
        """Return a datetime.timedelta that corresponds to this BatchExport's interval."""
        if self.interval == "hour":
            return timedelta(hours=1)
        elif self.interval == "day":
            return timedelta(days=1)
        elif self.interval == "week":
            return timedelta(weeks=1)
        elif self.interval.startswith("every"):
            _, value, unit = self.interval.split(" ")
            kwargs = {unit: int(value)}
            return timedelta(**kwargs)
        raise ValueError(f"Invalid interval: '{self.interval}'")


class BatchExportBackfill(UUIDModel):
    class Status(models.TextChoices):
        """Possible states of the BatchExportRun."""

        CANCELLED = "Cancelled"
        COMPLETED = "Completed"
        CONTINUED_AS_NEW = "ContinuedAsNew"
        FAILED = "Failed"
        FAILED_RETRYABLE = "FailedRetryable"
        TERMINATED = "Terminated"
        TIMEDOUT = "TimedOut"
        RUNNING = "Running"
        STARTING = "Starting"

    team = models.ForeignKey("Team", on_delete=models.CASCADE, help_text="The team this belongs to.")
    batch_export = models.ForeignKey(
        "BatchExport",
        on_delete=models.CASCADE,
        help_text="The BatchExport this backfill belongs to.",
    )
    start_at = models.DateTimeField(help_text="The start of the data interval.")
    end_at = models.DateTimeField(help_text="The end of the data interval.", null=True)
    status = models.CharField(choices=Status.choices, max_length=64, help_text="The status of this backfill.")
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="The timestamp at which this BatchExportBackfill was created.",
    )
    finished_at = models.DateTimeField(
        null=True,
        help_text="The timestamp at which this BatchExportBackfill finished, successfully or not.",
    )
    last_updated_at = models.DateTimeField(
        auto_now=True,
        help_text="The timestamp at which this BatchExportBackfill was last updated.",
    )

    @property
    def workflow_id(self) -> str:
        """Return the Workflow id that corresponds to this BatchExportBackfill model."""
        end_at = self.end_at and self.end_at.isoformat()
        return f"{self.batch_export.id}-Backfill-{self.start_at.isoformat()}-{end_at}"
