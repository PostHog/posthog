"""Enumerations the batch_exports models use.

A consumer that writes one of these values reads the enum from here and does not need the
model class. The models keep each enum as a class attribute (``BatchExportRun.Status``) so
existing call sites are unchanged. In an annotation the class attribute is not a valid type, so
annotate with the enum from this module directly.
"""

from posthog.enums import LabeledStrEnum


class BatchExportDestinationType(LabeledStrEnum):
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


class BatchExportModel(LabeledStrEnum):
    """The data model an export reads, for scheduled and on-demand exports alike."""

    EVENTS = "events"
    PERSONS = "persons"
    SESSIONS = "sessions"
    HOGQL = "hogql"


class BatchExportRunStatus(LabeledStrEnum):
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


class BatchExportBackfillStatus(LabeledStrEnum):
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


class BatchExportInterval(LabeledStrEnum):
    HOUR = "hour", "hour"
    DAY = "day", "day"
    WEEK = "week", "week"
    EVERY_5_MINUTES = "every 5 minutes", "every 5 minutes"
    EVERY_15_MINUTES = "every 15 minutes", "every 15 minutes"
