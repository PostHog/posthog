import os
from collections.abc import Callable
from datetime import datetime, timedelta
from functools import partial

import dagster
from dagster import Array, Backoff, DagsterRunStatus, Field, Jitter, RetryPolicy, RunsFilter, SkipReason
from tenacity import RetryError, retry, retry_if_result, stop_after_attempt, wait_exponential

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.settings.base_variables import DEBUG

TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS = os.getenv("TEAM_ID_FOR_WEB_ANALYTICS_ASSET_CHECKS", 1 if DEBUG else 2)

INTRA_DAY_HOURLY_CRON_SCHEDULE = os.getenv("WEB_PREAGGREGATED_INTRA_DAY_HOURLY_CRON_SCHEDULE", "*/20 * * * *")
HISTORICAL_DAILY_CRON_SCHEDULE = os.getenv("WEB_PREAGGREGATED_HISTORICAL_DAILY_CRON_SCHEDULE", "0 1 * * *")

WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT = os.getenv("WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT", "2200")

# Dagster execution timeout constants (should be higher than ClickHouse timeouts)
DAGSTER_WEB_JOB_TIMEOUT = int(os.getenv("WEB_PREAGGREGATED_DAGSTER_JOB_TIMEOUT", "2400"))


web_analytics_retry_policy_def = RetryPolicy(
    max_retries=3,
    delay=60,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.PLUS_MINUS,
)

# Shared ClickHouse settings for web analytics pre-aggregation
WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS = {
    "max_execution_time": WEB_PRE_AGGREGATED_CLICKHOUSE_TIMEOUT,
    "max_bytes_before_external_group_by": "51474836480",
    "max_memory_usage": "107374182400",
    "distributed_aggregation_memory_efficient": "1",
    "s3_truncate_on_insert": "1",
}

# Add higher partition limit for development environments (backfills)
if DEBUG:
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS["max_partitions_per_insert_block"] = "1000"


def format_clickhouse_settings(settings_dict: dict[str, str]) -> str:
    return ",".join([f"{key}={value}" for key, value in settings_dict.items()])


def merge_clickhouse_settings(base_settings: dict[str, str], extra_settings: str | None = None) -> str:
    settings = base_settings.copy()

    if extra_settings:
        # Parse extra settings string and merge
        for setting in extra_settings.split(","):
            if "=" in setting:
                key, value = setting.strip().split("=", 1)
                settings[key.strip()] = value.strip()

    return format_clickhouse_settings(settings)


def get_partitions(
    context: dagster.AssetExecutionContext,
    cluster: ClickhouseCluster,
    table_name: str,
    filter_by_partition_window: bool = False,
) -> list[str]:
    partition_query = f"SELECT DISTINCT partition FROM system.parts WHERE table = '{table_name}' AND active = 1"

    if filter_by_partition_window and context.partition_time_window:
        start_datetime, end_datetime = context.partition_time_window
        start_partition = start_datetime.strftime("%Y%m%d")
        end_partition = end_datetime.strftime("%Y%m%d")
        partition_query += f" AND partition >= '{start_partition}' AND partition < '{end_partition}'"

    context.log.info(f"Executing get_partitions query: {partition_query}")
    partitions_result = cluster.any_host_by_roles(
        lambda client: client.execute(partition_query), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ).result()
    context.log.info(f"Found {len(partitions_result)} partitions for {table_name}: {partitions_result}")
    return sorted([partition_row[0] for partition_row in partitions_result if partition_row and len(partition_row) > 0])


def drop_partitions_for_date_range(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, table_name: str, start_date: str, end_date: str
) -> None:
    current_date = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()

    while current_date < end_date_obj:
        partition_id = current_date.strftime("%Y%m%d")

        def drop_partition(client, pid):
            return client.execute(f"ALTER TABLE {table_name} DROP PARTITION '{pid}'")

        try:
            cluster.any_host_by_roles(
                partial(drop_partition, pid=partition_id), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
            ).result()
            context.log.info(f"Dropped partition {partition_id} from {table_name}")
        except Exception as e:
            context.log.info(f"Partition {partition_id} doesn't exist or couldn't be dropped: {e}")

        current_date += timedelta(days=1)


def get_expected_partitions_from_time_window(
    context: dagster.AssetExecutionContext,
) -> list[str]:
    if not context.partition_time_window:
        raise dagster.Failure("partition_time_window is required to determine expected partitions")

    start_datetime, end_datetime = context.partition_time_window
    current_date = start_datetime.date()
    end_date = end_datetime.date()

    partitions = []
    while current_date < end_date:
        partitions.append(current_date.strftime("%Y%m%d"))
        current_date += timedelta(days=1)

    return partitions


def sync_partitions_on_replicas(
    context: dagster.AssetExecutionContext,
    cluster: ClickhouseCluster,
    target_table: str,
    validate_after_sync: bool = True,
) -> None:
    context.log.info(f"Syncing replicas for {target_table} on all hosts")
    cluster.map_hosts_by_roles(
        lambda client: client.execute(f"SYSTEM SYNC REPLICA {target_table}"),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ).result()

    # Validate expected partitions exist after sync
    if validate_after_sync and context.partition_time_window:
        expected_partitions = get_expected_partitions_from_time_window(context)
        context.log.info(f"Validating expected partitions after sync: {expected_partitions}")
        validate_partitions_on_all_hosts(context, cluster, target_table, expected_partitions)


def _query_partitions_from_hosts(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, query: str
) -> dict:
    context.log.info(f"Executing partition validation query: {query}")

    def execute_query(client, query=query):
        return client.execute(query)

    return cluster.map_hosts_by_roles(
        execute_query,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ).result()


def _validate_host_partition_result(
    host_key: str, result, expected_partitions: list[str], context: dagster.AssetExecutionContext
) -> tuple[bool, list[str] | None]:
    if result.error:
        # Query errors should fail immediately, not retry
        error_msg = f"Error querying host {host_key}: {result.error}"
        context.log.error(error_msg)
        raise dagster.Failure(error_msg)

    if not result.value or len(result.value) == 0:
        context.log.warning(f"No partition data returned from host {host_key}")
        return False, expected_partitions

    # Extract partitions from result
    host_name = result.value[0][0] if result.value[0] else host_key
    found_partitions = result.value[0][1] if len(result.value[0]) > 1 else []

    # Check for missing partitions
    missing = set(expected_partitions) - set(found_partitions)
    if missing:
        context.log.warning(f"Host {host_name} missing partitions: {sorted(missing)}. Found: {found_partitions}")
        return False, sorted(missing)

    context.log.info(f"Host {host_name} has all expected partitions: {found_partitions}")
    return True, None


def _get_missing_partitions_on_all_hosts(
    context: dagster.AssetExecutionContext,
    cluster: ClickhouseCluster,
    table_name: str,
    expected_partitions: list[str],
) -> dict[str, list[str]] | None:
    query = f"""
        SELECT
            hostName() as host,
            arraySort(groupArray(DISTINCT partition)) as partitions
        FROM system.parts
        WHERE table = '{table_name}'
            AND active = 1
            AND partition IN ({','.join([f"'{p}'" for p in expected_partitions])})
        GROUP BY host
    """
    host_results = _query_partitions_from_hosts(context, cluster, query)

    all_hosts_valid = True
    missing_partitions_by_host = {}

    for host_key, result in host_results.items():
        is_valid, missing_partitions = _validate_host_partition_result(host_key, result, expected_partitions, context)

        if not is_valid:
            all_hosts_valid = False
            if missing_partitions:
                missing_partitions_by_host[host_key] = missing_partitions

    if all_hosts_valid:
        context.log.info(f"All hosts validated successfully for table {table_name}")
        return None

    return missing_partitions_by_host


def validate_partitions_on_all_hosts(
    context: dagster.AssetExecutionContext,
    cluster: ClickhouseCluster,
    table_name: str,
    expected_partitions: list[str],
    max_retries: int = 3,
    retry_delay: int = 5,
) -> None:
    context.log.info(f"Starting partition validation for table {table_name} with partitions: {expected_partitions}")

    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=1, min=retry_delay, max=retry_delay * 4),
        retry=retry_if_result(lambda result: result is not None and len(result) > 0),
        reraise=True,
    )
    def _validate_partitions_with_retry():
        attempt = (
            getattr(_validate_partitions_with_retry.retry.statistics.get("attempt_number", 1), "value", 1)
            if hasattr(_validate_partitions_with_retry, "retry")
            else 1
        )
        context.log.info(f"Validating partitions on all hosts (attempt {attempt}/{max_retries})")

        missing_partitions_by_host = _get_missing_partitions_on_all_hosts(
            context, cluster, table_name, expected_partitions
        )

        if missing_partitions_by_host:
            context.log.warning(
                f"Partition validation found missing partitions: {missing_partitions_by_host}. "
                f"Will retry with exponential backoff…"
            )
            # Try syncing before the next attempt (without validation to avoid recursion)
            sync_partitions_on_replicas(context, cluster, table_name, validate_after_sync=False)

        return missing_partitions_by_host

    # Execute the validation with retries
    try:
        result = _validate_partitions_with_retry()
        if result is None:
            # Success - all partitions validated
            return
    except RetryError as e:
        # All retries exhausted
        last_result = e.last_attempt.result() if not e.last_attempt.failed else None
        error_msg = (
            f"Partition validation failed after {max_retries} attempts for table {table_name}. "
            f"Expected partitions: {expected_partitions}. "
            f"Missing partitions by host: {last_result if last_result else 'Unknown'}"
        )
        context.log.error(error_msg)  # noqa: TRY400
        raise dagster.Failure(error_msg)


def swap_partitions_from_staging(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, target_table: str, staging_table: str
) -> None:
    if not context.partition_time_window:
        raise dagster.Failure("partition_time_window is required for swapping partitions")

    expected_partitions = get_expected_partitions_from_time_window(context)
    context.log.info(f"Swapping partitions {expected_partitions} from {staging_table} to {target_table}")

    # Validate partitions exist on staging table before swapping
    if expected_partitions:
        validate_partitions_on_all_hosts(context, cluster, staging_table, expected_partitions)

    def replace_partition(client, pid):
        return client.execute(f"ALTER TABLE {target_table} REPLACE PARTITION '{pid}' FROM {staging_table}")

    for partition_id in expected_partitions:
        cluster.any_host_by_roles(
            partial(replace_partition, pid=partition_id), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
        ).result()


def clear_all_staging_partitions(
    context: dagster.AssetExecutionContext, cluster: ClickhouseCluster, staging_table: str
) -> None:
    all_partitions = get_partitions(context, cluster, staging_table, filter_by_partition_window=False)

    if not all_partitions:
        context.log.info(f"No partitions found in {staging_table}")
        return

    context.log.info(f"Clearing {len(all_partitions)} partitions from {staging_table}: {all_partitions}")

    def drop_partition(client, pid):
        return client.execute(f"ALTER TABLE {staging_table} DROP PARTITION '{pid}'")

    for partition_id in all_partitions:
        try:
            cluster.any_host_by_roles(
                partial(drop_partition, pid=partition_id), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
            ).result()
            context.log.info(f"Dropped partition {partition_id} from {staging_table}")
        except Exception as e:
            context.log.warning(f"Failed to drop partition {partition_id} from {staging_table}: {e}")


def recreate_staging_table(
    context: dagster.AssetExecutionContext,
    cluster: ClickhouseCluster,
    staging_table: str,
    replace_sql_func: Callable[[], str],
) -> None:
    context.log.info(f"Recreating staging table {staging_table}")
    # We generate a uuid with force_unique_zk_path=True, which we want to be unique per the cluster
    # so we must get the result statement string here instead of inside the lambda to run the
    # exact command on each host, otherwise we would get a new uuid per host and replication
    # woudn't kick in.
    sql_statement = replace_sql_func()
    cluster.map_hosts_by_roles(
        lambda client: client.execute(sql_statement), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]
    ).result()


# Shared config schema for daily processing
WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        is_required=False,
        description="List of team IDs to process - if not provided, uses ClickHouse dictionary configuration",
    ),
    "extra_clickhouse_settings": Field(
        str,
        default_value="",
        description="Additional ClickHouse execution settings to merge with defaults",
    ),
}


def check_for_concurrent_runs(context: dagster.ScheduleEvaluationContext) -> SkipReason | None:
    # Get the schedule name from the context
    schedule_name = context._schedule_name

    # Get the schedule definition from the repository to find the associated job
    schedule_def = context.repository_def.get_schedule_def(schedule_name)
    job_name = schedule_def.job_name

    run_records = context.instance.get_run_records(
        RunsFilter(
            job_name=job_name,
            statuses=[
                DagsterRunStatus.QUEUED,
                DagsterRunStatus.NOT_STARTED,
                DagsterRunStatus.STARTING,
                DagsterRunStatus.STARTED,
            ],
        )
    )

    if len(run_records) > 0:
        context.log.info(f"Skipping {job_name} due to {len(run_records)} active run(s)")
        return SkipReason(f"Skipping {job_name} run because another run of the same job is already active")

    return None
