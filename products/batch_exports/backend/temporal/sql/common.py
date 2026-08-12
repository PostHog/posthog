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
