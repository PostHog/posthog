from dataclasses import dataclass
from uuid import UUID
from django.db import models, transaction

from asgiref.sync import sync_to_async
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


@dataclass
class BatchExportDestinationData:
    """
    Static structures that we can easily pass around to, e.g. asyncio tasks.
    """

    type: str
    config: dict


@dataclass
class BatchExportData:
    """
    Static structures that we can easily pass around to, e.g. asyncio tasks.
    """

    id: UUID
    team_id: int
    name: str
    interval: str
    destination: BatchExportDestinationData


def acreate_batch_export(
    team_id: int, name: str, type: str, config: dict, interval: str, paused: bool = False
) -> BatchExportData:
    """
    Creates a BatchExport for a given team, destination, and interval.

    :param team: The team to create the BatchExport for.
    :param name: The name of the BatchExport.
    :param destination: The destination to export data to.
    :param interval: The interval at which to export data.
    :param paused: Whether the BatchExport should be paused or not.
    :return: The created BatchExport.
    """
    with transaction.atomic():
        destination = BatchExportDestination.objects.create(type=type, config=config)
        export = BatchExport.objects.create(
            team_id=team_id, name=name, destination=destination, interval=interval, paused=paused
        )

    return BatchExportData(
        id=export.id,
        team_id=export.team_id,
        name=export.name,
        interval=export.interval,
        destination=BatchExportDestinationData(
            type=export.destination.type,
            config=export.destination.config,
        ),
    )


def fetch_batch_export(batch_export_id: UUID) -> BatchExport | None:
    """
    Fetch a BatchExport by id.
    """
    try:
        export_row = BatchExport.objects.values(
            "id", "team_id", "name", "interval", "destination__type", "destination__config"
        ).get(id=batch_export_id)
    except BatchExport.DoesNotExist:
        return None

    return BatchExport(
        id=export_row["id"],
        team_id=export_row["team_id"],
        name=export_row["name"],
        interval=export_row["interval"],
        destination=BatchExportDestination(
            type=export_row["destination__type"],
            config=export_row["destination__config"],
        ),
    )


async def afetch_batch_export(batch_export_id: UUID) -> BatchExport | None:
    """
    Fetch a BatchExport by id.
    """
    return await sync_to_async(fetch_batch_export)(batch_export_id)  # type: ignore
