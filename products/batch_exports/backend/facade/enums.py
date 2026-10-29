"""Enumerations and fixed value sets the batch_exports models and API use.

A consumer that writes one of these values reads the enum from here and does not need the
model class. The models keep each enum as a class attribute (``BatchExportRun.Status``) so
existing call sites are unchanged. In an annotation the class attribute is not a valid type, so
annotate with the enum from this module directly.

The value sets at the end of the module are the single source for the models, the Temporal
destinations and the API serializers, so they must stay free of framework imports.
"""

import pytz

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


class IncrementalMode(LabeledStrEnum):
    """Different modes to handle incremental updates."""

    APPEND = "APPEND"
    MERGE = "MERGE"
    # TODO: Add 'FULL_REFRESH': data is re-created on every run.


# this is what is used by the Team model
# (we could use common_timezones instead; this has 433 timezones vs 596 for all_timezones)
TIMEZONES = [(tz, tz) for tz in pytz.all_timezones]

S3_FAMILY_TYPES: frozenset[str] = frozenset(
    {BatchExportDestinationType.AWS_S3, BatchExportDestinationType.S3_COMPATIBLE}
)

# Destinations that write files to object storage, as opposed to the data warehouse destinations
# (BigQuery, Databricks, Postgres, Redshift, Snowflake) that write rows into a table. File format,
# compression and object key layout are questions only this half has to answer.
#
# Also includes "FileDownload", which writes to a PostHog bucket rather than a customer one.
# TODO: it probably makes sense to introduce a 'DestinationKind' abstraction in the future,
# to properly categorize object storage and data warehouse destinations.
OBJECT_STORAGE_DESTINATIONS: frozenset[str] = frozenset(
    {
        BatchExportDestinationType.AWS_S3,
        BatchExportDestinationType.S3_COMPATIBLE,
        BatchExportDestinationType.AZURE_BLOB,
        BatchExportDestinationType.FILE_DOWNLOAD,
    }
)

# The integration kinds that a batch export destination can use for credentials.
BATCH_EXPORT_INTEGRATION_KINDS: tuple[str, ...] = (
    "aws-redshift",
    "aws-s3",
    "azure-blob",
    "databricks",
    "google-cloud-service-account",
    "postgresql",
    "s3-compatible",
    "snowflake",
)

S3_SUPPORTED_COMPRESSIONS: dict[str, list[str]] = {
    "Parquet": ["zstd", "lz4", "snappy", "gzip", "brotli"],
    "JSONLines": ["gzip", "brotli"],
}

AZURE_BLOB_SUPPORTED_COMPRESSIONS: dict[str, list[str]] = {
    "Parquet": ["zstd", "lz4", "snappy", "gzip", "brotli"],
    "JSONLines": ["gzip", "brotli"],
}

# Projected columns a HogQL query can select.
# NOTE: this is just for the 'old' version of our HogQL support, where a user can define a custom
# SELECT FROM clause, useful for defining a custom schema. It's not related to the new HogQL model,
# in which a user can use any arbitrary SELECT query.
EXPORTABLE_EVENTS_MODEL_FIELDS = frozenset(
    {
        "team_id",
        "timestamp",
        "event",
        "distinct_id",
        "uuid",
        "created_at",
        "elements_chain",
        "person_id",
        "properties",
        "person_properties",
    }
)

# Single source of truth for the serialized filter `type` values we accept. Enforced at write
# time by `validate_batch_export_filters` and at query time by `compose_filters_clause`.
SUPPORTED_FILTER_TYPES = frozenset({"event", "person", "hogql"})

# Quoted, sorted rendering of the supported filter types for user-facing messages.
SUPPORTED_FILTER_TYPES_DISPLAY = ", ".join(repr(t) for t in sorted(SUPPORTED_FILTER_TYPES))
