"""Enumerations the batch_exports models use.

A consumer that writes one of these values reads the enum from here and does not need the
model class. This is a contract file, so it has no Django imports. Each enum has a
``(value, label)`` choices list next to it, which the model fields, the serializer
``ChoiceField``s and the OpenAPI enum names use.

The models keep each enum as a class attribute (``BatchExportRun.Status``) so existing call
sites are unchanged. In an annotation the class attribute is not a valid type, so annotate
with the enum from this module directly.
"""

from enum import StrEnum


def _label(member: StrEnum) -> str:
    # Django derives the same label for a TextChoices member without an explicit one. A
    # different label changes the field choices, and makemigrations then writes an AlterField.
    return member.name.replace("_", " ").title()


class DestinationType(StrEnum):
    """Enumeration of supported destinations for PostHog BatchExports."""

    AWS_S3 = "AwsS3"
    S3_COMPATIBLE = "S3Compatible"
    SNOWFLAKE = "Snowflake"
    POSTGRES = "Postgres"
    REDSHIFT = "Redshift"
    BIGQUERY = "BigQuery"
    DATABRICKS = "Databricks"
    AZURE_BLOB = "AzureBlob"
    WORKFLOWS = "Workflows"
    HTTP = "HTTP"
    NOOP = "NoOp"
    FILE_DOWNLOAD = "FileDownload"


DESTINATION_TYPE_CHOICES = [(member.value, _label(member)) for member in DestinationType]


class BatchExportModel(StrEnum):
    """The data model an export reads, for scheduled and on-demand exports alike."""

    EVENTS = "events"
    PERSONS = "persons"
    SESSIONS = "sessions"
    HOGQL = "hogql"


BATCH_EXPORT_MODEL_CHOICES = [(member.value, _label(member)) for member in BatchExportModel]


class BatchExportRunStatus(StrEnum):
    """Possible states of the BatchExportRun."""

    CANCELLED = "Cancelled"
    COMPLETED = "Completed"
    CONTINUED_AS_NEW = "ContinuedAsNew"
    FAILED = "Failed"
    FAILED_RETRYABLE = "FailedRetryable"
    FAILED_BILLING = "FailedBilling"
    TERMINATED = "Terminated"
    TIMEDOUT = "TimedOut"
    RUNNING = "Running"
    STARTING = "Starting"


BATCH_EXPORT_RUN_STATUS_CHOICES = [(member.value, _label(member)) for member in BatchExportRunStatus]


class BatchExportBackfillStatus(StrEnum):
    """Possible states of the BatchExportBackfill."""

    CANCELLED = "Cancelled"
    COMPLETED = "Completed"
    CONTINUED_AS_NEW = "ContinuedAsNew"
    FAILED = "Failed"
    FAILED_RETRYABLE = "FailedRetryable"
    TERMINATED = "Terminated"
    TIMEDOUT = "TimedOut"
    RUNNING = "Running"
    STARTING = "Starting"


BATCH_EXPORT_BACKFILL_STATUS_CHOICES = [(member.value, _label(member)) for member in BatchExportBackfillStatus]


class BatchExportInterval(StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    EVERY_5_MINUTES = "every 5 minutes"
    EVERY_15_MINUTES = "every 15 minutes"


# The interval labels are the values, not the labels that _label derives.
BATCH_EXPORT_INTERVALS = [(interval.value, interval.value) for interval in BatchExportInterval]
