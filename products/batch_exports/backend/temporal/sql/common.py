import typing

from django.conf import settings

from posthog.hogql.constants import HogQLQuerySettings

from posthog.credentials import AWSKeyPair


def get_s3_function_call(s3_folder: str, credentials: AWSKeyPair | None, num_partitions: int) -> str:
    """Generate the s3() function call for ClickHouse INSERT queries.

    When using keyless S3 auth (IAM roles), we omit credentials and ClickHouse uses the
    default credential provider chain. Otherwise, we pass the access key and secret.

    Note: We use %% for the modulo operator because the ClickHouse client uses % for
    parameter substitution, so %% produces a literal % in the final query.
    """
    s3_url = f"{s3_folder}/export_{{{{_partition_id}}}}.arrow"
    if credentials is not None:
        # Escape single quotes by doubling them (ClickHouse SQL escaping)
        escaped_key = credentials.access_key_id.replace("'", "''")
        escaped_secret = credentials.secret_access_key.replace("'", "''")
        s3_call = f"s3('{s3_url}', '{escaped_key}', '{escaped_secret}', 'ArrowStream')"
    else:
        s3_call = f"s3('{s3_url}', 'ArrowStream')"

    return f"""{s3_call}
    PARTITION BY rand() %% {num_partitions}"""


class BatchExportQuerySettings(HogQLQuerySettings):
    optimize_aggregation_in_order: bool | None = True
    max_bytes_before_external_sort: int | None = 50000000000
    max_bytes_before_external_group_by: int | None = 50000000000


class UserHogQLBatchExportQuerySettings(BatchExportQuerySettings):
    """Settings for a batch export powered by an arbitrary user-supplied HogQL query.

    User-supplied queries are a lot more unpredictable than our own queries for
    events/persons/sessions, so we need to set some resource limits to prevent them consuming all
    available resources, which could negatively impact other batch exports.
    """

    max_execution_time: int | None = None
    max_memory_usage: int | None = None

    # These are ClickHouse's own defaults but we pin them here just to be sure (setting them to
    # 'break' for example would allow for queries to return partial data on failure).
    read_overflow_mode: typing.Literal["throw", "break"] | None = "throw"
    timeout_overflow_mode: typing.Literal["throw", "break"] | None = "throw"
    # Must be 0 or the absolute `max_bytes_before_external_*` thresholds do nothing: a non-zero ratio
    # (0.5 by default) measures against *available server* memory instead, which on a large node sits
    # far above any per-query cap.
    max_bytes_ratio_before_external_sort: float | None = 0.0
    max_bytes_ratio_before_external_group_by: float | None = 0.0


def get_user_hogql_batch_export_query_settings() -> UserHogQLBatchExportQuerySettings:
    """Build the user-query settings, reading Django settings at call time so `@override_settings` works."""
    max_memory_usage = settings.BATCH_EXPORT_HOGQL_MAX_MEMORY_USAGE
    # Spill sorts and aggregations to disk at this share of the query's memory cap. Halfway leaves room
    # to finish the spilled work within the cap.
    spill_after_bytes = int(max_memory_usage * 0.5)
    return UserHogQLBatchExportQuerySettings(
        max_execution_time=settings.BATCH_EXPORT_HOGQL_MAX_EXECUTION_TIME,
        max_memory_usage=max_memory_usage,
        max_bytes_before_external_sort=spill_after_bytes,
        max_bytes_before_external_group_by=spill_after_bytes,
        max_bytes_to_read=settings.BATCH_EXPORT_HOGQL_MAX_BYTES_TO_READ,
    )
