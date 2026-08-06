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


class HogQLQueryBatchExportSettings(HogQLQuerySettings):
    optimize_aggregation_in_order: bool | None = True
    max_bytes_before_external_sort: int | None = 50000000000
    max_bytes_before_external_group_by: int | None = 50000000000


# Spill sorts and aggregations to disk once they reach this share of the query's memory cap. Halfway
# leaves the query room to finish the spilled work within its cap while still cutting peak memory
# several-fold (measured ~8x on a sort that would otherwise hold its whole buffer in memory).
_EXTERNAL_SPILL_SHARE_OF_MEMORY_CAP = 0.5


class HogQLUserQueryBatchExportSettings(HogQLQueryBatchExportSettings):
    """Settings for a batch export powered by an arbitrary user-supplied HogQL query.

    Adds the per-query resource fences the fixed models (events/persons/sessions) don't need,
    because those queries are ours and predictable: an execution-time cap, a memory cap, a read
    backstop, and disk spilling that actually engages.

    The overflow modes are pinned to `throw` defensively rather than to change ClickHouse's own
    default, which is already `throw`. A cluster profile is free to set them to `break`, under which a
    query that hits the time or read limit returns a *partial* result with a normal `QueryFinish` —
    silently truncating the export instead of failing it. Since the limits above are what stands
    between a user query and the cluster, it is worth not inheriting that.
    """

    max_execution_time: int | None = None
    max_memory_usage: int | None = None
    timeout_overflow_mode: str | None = None
    # These must be 0 for the absolute `max_bytes_before_external_*` thresholds to do anything. A
    # non-zero ratio (0.5 by default) hands the spill decision to a proportion of *available server*
    # memory and demotes the absolute threshold to a minimum block size, so on a large node — where
    # half of available memory is far above a per-query cap — a sort never spills and the query is
    # killed at its cap instead. Verified against ClickHouse 26.6: same sort, same absolute threshold,
    # 686MiB peak and no spill with the default ratio versus 83MiB peak and 14 spill files with it at 0.
    max_bytes_ratio_before_external_sort: float | None = None
    max_bytes_ratio_before_external_group_by: float | None = None


def get_hogql_user_query_batch_export_settings() -> HogQLUserQueryBatchExportSettings:
    """Build the user-query settings from Django settings.

    Read at call time (not at import) so tests can drive the values with `@override_settings`.
    """
    max_memory_usage = settings.BATCH_EXPORT_HOGQL_MAX_MEMORY_USAGE
    # Derived from the memory cap rather than configured separately: a spill threshold above the cap is
    # silently useless (the query dies before reaching it), so the two cannot be allowed to drift apart.
    spill_after_bytes = int(max_memory_usage * _EXTERNAL_SPILL_SHARE_OF_MEMORY_CAP)
    return HogQLUserQueryBatchExportSettings(
        max_execution_time=settings.BATCH_EXPORT_HOGQL_MAX_EXECUTION_TIME,
        max_memory_usage=max_memory_usage,
        max_bytes_before_external_sort=spill_after_bytes,
        max_bytes_before_external_group_by=spill_after_bytes,
        max_bytes_ratio_before_external_sort=0,
        max_bytes_ratio_before_external_group_by=0,
        max_bytes_to_read=settings.BATCH_EXPORT_HOGQL_MAX_BYTES_TO_READ,
        read_overflow_mode="throw",
        timeout_overflow_mode="throw",
    )
