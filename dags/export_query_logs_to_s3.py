import datetime
from typing import ClassVar

import dagster
import pydantic
from clickhouse_driver import Client

from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.settings.base_variables import DEBUG
from posthog.settings.dagster import DAGSTER_DATA_EXPORT_S3_BUCKET
from posthog.settings.object_storage import (
    OBJECT_STORAGE_ACCESS_KEY_ID,
    OBJECT_STORAGE_ENDPOINT,
    OBJECT_STORAGE_SECRET_ACCESS_KEY,
)

from dags.common import ClickhouseClusterResource, settings_with_log_comment


class DateRange(dagster.Config):
    date_from: str  # Format: YYYY-MM-DD
    date_to: str  # Format: YYYY-MM-DD

    FORMAT: ClassVar[str] = "%Y-%m-%d"

    @pydantic.field_validator("date_from", "date_to")
    @classmethod
    def validate_format(cls, value: str) -> str:
        cls.parse_date(value)
        return value

    @pydantic.model_validator(mode="after")
    def validate_bounds(self):
        if not self.parse_date(self.date_from) <= self.parse_date(self.date_to):
            raise ValueError("expected date_from to be less than (or equal to) date_to")
        return self

    @classmethod
    def parse_date(cls, value: str) -> datetime.date:
        return datetime.datetime.strptime(value, cls.FORMAT).date()


class QueryLogsExportConfig(dagster.Config):
    date_range: DateRange = None  # Optional, if not provided will use yesterday's date
    s3_path: str = "query_logs"  # Subdirectory in the S3 bucket


@dagster.op
def export_query_logs(
    context: dagster.OpExecutionContext,
    config: QueryLogsExportConfig,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """
    Export ClickHouse query logs to S3 using ClickHouse's native S3 export functionality.
    Exports all columns from the system.query_log table for the specified date range.
    """
    # If date_range is not provided, use yesterday's date
    if config.date_range is None:
        yesterday = datetime.date.today() - datetime.timedelta(days=1)
        date_from = yesterday
        date_to = yesterday
    else:
        date_from = DateRange.parse_date(config.date_range.date_from)
        date_to = DateRange.parse_date(config.date_range.date_to)

    # We'll create a function that generates the query for each host
    # This allows us to include the hostname in the filename to avoid conflicts
    def generate_export_query(client: Client):
        # Get the hostname from the client
        [[hostname]] = client.execute("SELECT hostName()")

        context.log.info(
            f"Starting export of query logs from {date_from} to {date_to} on host {hostname} with run ID {context.run.run_id}"
        )

        # For each date in the range, create a separate export
        # This ensures proper Hive partitioning by date
        current_date = date_from
        while current_date <= date_to:
            for is_initial_query in [0, 1]:
                date_s3_filename = f"{config.s3_path}/event_date={current_date.strftime('%Y-%m-%d')}/is_initial_query={is_initial_query}/{hostname}_{context.run.run_id}.parquet"

                if DEBUG:
                    date_s3_path = f"{OBJECT_STORAGE_ENDPOINT}/{DAGSTER_DATA_EXPORT_S3_BUCKET}/{date_s3_filename}"
                    date_s3_function_args = (
                        f"'{date_s3_path}', "
                        f"'{OBJECT_STORAGE_ACCESS_KEY_ID}', "
                        f"'{OBJECT_STORAGE_SECRET_ACCESS_KEY}', "
                        f"'Parquet'"
                    )
                else:
                    date_s3_path = f"https://{DAGSTER_DATA_EXPORT_S3_BUCKET}.s3.amazonaws.com/{date_s3_filename}"
                    date_s3_function_args = f"'{date_s3_path}', 'Parquet'"

                # Construct the export query for this specific date
                # Explicitly select all columns except transaction_id which contains a UUID that Parquet doesn't support
                query = f"""
                INSERT INTO FUNCTION s3({date_s3_function_args})
                SELECT
                    hostname,
                    type,
                    event_date,
                    event_time,
                    event_time_microseconds,
                    query_start_time,
                    query_start_time_microseconds,
                    query_duration_ms,
                    read_rows,
                    read_bytes,
                    written_rows,
                    written_bytes,
                    result_rows,
                    result_bytes,
                    memory_usage,
                    current_database,
                    query,
                    formatted_query,
                    normalized_query_hash,
                    query_kind,
                    databases,
                    tables,
                    columns,
                    partitions,
                    projections,
                    views,
                    exception_code,
                    exception,
                    stack_trace,
                    is_initial_query,
                    user,
                    query_id,
                    address,
                    port,
                    initial_user,
                    initial_query_id,
                    initial_address,
                    initial_port,
                    initial_query_start_time,
                    initial_query_start_time_microseconds,
                    interface,
                    is_secure,
                    os_user,
                    client_hostname,
                    client_name,
                    client_revision,
                    client_version_major,
                    client_version_minor,
                    client_version_patch,
                    http_method,
                    http_user_agent,
                    http_referer,
                    forwarded_for,
                    quota_key,
                    distributed_depth,
                    revision,
                    log_comment,
                    thread_ids,
                    peak_threads_usage,
                    ProfileEvents,
                    Settings,
                    used_aggregate_functions,
                    used_aggregate_function_combinators,
                    used_database_engines,
                    used_data_type_families,
                    used_dictionaries,
                    used_formats,
                    used_functions,
                    used_storages,
                    used_table_functions,
                    used_row_policies,
                    used_privileges,
                    missing_privileges,
                    -- transaction_id is excluded because it contains a UUID which Parquet doesn't support
                    query_cache_usage,
                    asynchronous_read_counters,
                    ProfileEvents.Names,
                    ProfileEvents.Values,
                    Settings.Names,
                    Settings.Values,
                    -- Extracted columns
                    JSONExtractInt(log_comment, 'team_id') as team_id,
                    JSONExtractString(log_comment, 'workload') as workload
                FROM system.query_log
                WHERE event_date = toDate(%(current_date)s) AND is_initial_query = {is_initial_query}
                SETTINGS s3_truncate_on_insert=1
                """

                context.log.info(
                    f"Exporting query logs for {current_date} to {date_s3_path} on host {hostname}, is_initial_query={is_initial_query}"
                )

                # Execute the query for this date
                client.execute(
                    query,
                    {
                        "current_date": current_date.strftime(DateRange.FORMAT),
                    },
                    settings=settings_with_log_comment(context),
                )

            # Move to the next date
            current_date += datetime.timedelta(days=1)

        # Return a summary of the export
        return f"Exported query logs from {date_from} to {date_to}"

    # Execute the query on all hosts in the cluster
    context.log.info(f"Starting export of query logs from {date_from} to {date_to} on all hosts")
    results = cluster.map_all_hosts(generate_export_query).result()

    # Log the results
    for host, result in results.items():
        context.log.info(f"Export completed on host {host}: {result}")

    context.log.info(f"Query logs export completed successfully on all hosts")


@dagster.job(resource_defs={"cluster": ClickhouseClusterResource()})
def export_query_logs_to_s3():
    export_query_logs()


# Schedule to run query logs export at 1 AM daily
query_logs_export_schedule = dagster.ScheduleDefinition(
    job=export_query_logs_to_s3,
    cron_schedule="0 1 * * *",  # At 01:00 (1 AM) every day
    execution_timezone="UTC",
    name="query_logs_export_schedule",
)
