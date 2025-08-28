import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import dagster
import structlog
from dagster import BackfillPolicy, DailyPartitionsDefinition

from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.models.web_preaggregated.sql import (
    DROP_PARTITION_SQL,
    WEB_BOUNCES_EXPORT_SQL,
    WEB_BOUNCES_INSERT_SQL,
    WEB_STATS_EXPORT_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.models.web_preaggregated.team_selection import WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME
from posthog.settings.base_variables import DEBUG
from posthog.settings.object_storage import OBJECT_STORAGE_ENDPOINT, OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET

from dags.common import JobOwners, dagster_tags
from dags.web_preaggregated_utils import (
    DAGSTER_WEB_JOB_TIMEOUT,
    HISTORICAL_DAILY_CRON_SCHEDULE,
    WEB_ANALYTICS_CONFIG_SCHEMA,
    WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS,
    check_for_concurrent_runs,
    merge_clickhouse_settings,
    web_analytics_retry_policy_def,
)

logger = structlog.get_logger(__name__)

# From my tests, 14 (two weeks) is a sane value for production.
# But locally we can run more partitions per run to speed up testing (e.g: 3000 to materialize everything on a single run)
max_partitions_per_run = int(os.getenv("DAGSTER_WEB_PREAGGREGATED_MAX_PARTITIONS_PER_RUN", 14))
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=max_partitions_per_run)

partition_def = DailyPartitionsDefinition(start_date="2020-01-01")


def pre_aggregate_web_analytics_data(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Pre-aggregate web analytics data for a given table and date range.

    Args:
        context: Dagster execution context
        table_name: Target table name (web_stats_daily or web_bounces_daily)
        sql_generator: Function to generate SQL query
        cluster: ClickHouse cluster resource
    """
    config = context.op_config
    # Use dictionary lookup by default, fallback to config if provided
    team_ids = config.get("team_ids")  # None = use dictionary, list = use IN clause

    extra_settings = config.get("extra_clickhouse_settings", "")
    ch_settings = merge_clickhouse_settings(WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS, extra_settings)

    if not context.partition_time_window:
        raise dagster.Failure("This asset should only be run with a partition_time_window")

    context.log.info(f"Getting ready to pre-aggregate {table_name} for {context.partition_time_window}")

    start_datetime, end_datetime = context.partition_time_window
    date_start = start_datetime.strftime("%Y-%m-%d")
    date_end = end_datetime.strftime("%Y-%m-%d")

    try:
        # Drop all partitions in the time window, ensuring a clean state before insertion
        # Note: No ON CLUSTER needed since tables are replicated (not sharded) and replication handles distribution
        current_date = start_datetime.date()
        end_date = end_datetime.date()

        # For time windows: start is inclusive, end is exclusive (except for single-day partitions)
        while current_date < end_date or (current_date == start_datetime.date() == end_date):
            partition_date_str = current_date.strftime("%Y-%m-%d")
            drop_partition_query = DROP_PARTITION_SQL(table_name, partition_date_str, granularity="daily")
            context.log.info(f"Dropping partition for {partition_date_str}: {drop_partition_query}")

            try:
                sync_execute(drop_partition_query)
                context.log.info(f"Successfully dropped partition for {partition_date_str}")
            except Exception as drop_error:
                # Partition might not exist when running for the first time or when running in a empty backfill, which is fine
                context.log.info(
                    f"Partition for {partition_date_str} doesn't exist or couldn't be dropped: {drop_error}"
                )

            current_date += timedelta(days=1)

        insert_query = sql_generator(
            date_start=date_start,
            date_end=date_end,
            team_ids=team_ids,
            settings=ch_settings,
            table_name=table_name,
        )

        # Intentionally log query details for debugging
        context.log.info(insert_query)

        sync_execute(insert_query)

    except Exception as e:
        raise dagster.Failure(f"Failed to pre-aggregate {table_name}: {str(e)}") from e


@dagster.asset(
    name="web_analytics_bounces_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_bounces_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_bounces_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Daily bounce rate data for web analytics.

    Aggregates bounce rate, session duration, and other session-level metrics
    by various dimensions (UTM parameters, geography, device info, etc.).
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_bounces_daily",
        sql_generator=WEB_BOUNCES_INSERT_SQL,
        cluster=cluster,
    )


@dagster.asset(
    name="web_analytics_stats_table_daily",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "web_stats_daily"},
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
    retry_policy=web_analytics_retry_policy_def,
)
def web_stats_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Aggregated dimensional data with pageviews and unique user counts.

    Aggregates pageview counts, unique visitors, and unique sessions
    by various dimensions (pathnames, UTM parameters, geography, device info, etc.).
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return pre_aggregate_web_analytics_data(
        context=context,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
        cluster=cluster,
    )


def export_web_analytics_data_by_team(
    context: dagster.AssetExecutionContext,
    table_name: str,
    sql_generator: Callable,
    export_prefix: str,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.Output[list]:
    config = context.op_config
    # Use dictionary lookup by default, fallback to config if provided
    team_ids = config.get("team_ids")  # None = use dictionary, list = use IN clause

    ch_settings = merge_clickhouse_settings(
        WEB_PRE_AGGREGATED_CLICKHOUSE_SETTINGS, config.get("extra_clickhouse_settings", "")
    )

    if not team_ids:
        dict_query = f"SELECT team_id FROM {WEB_PRE_AGGREGATED_TEAM_SELECTION_TABLE_NAME} FINAL"
        try:
            result = sync_execute(dict_query)
            team_ids = [row[0] for row in result]
            context.log.info(f"Retrieved {len(team_ids)} team IDs from dictionary for export")
        except Exception as e:
            context.log.info(f"Failed to retrieve team IDs from dictionary: {e}")
            raise dagster.Failure(f"Failed to retrieve team IDs from dictionary: {e}")

    successfully_exported_paths = []
    failed_team_ids = []

    for team_id in team_ids:
        if DEBUG:
            team_s3_path = f"{OBJECT_STORAGE_ENDPOINT}/{OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET}/{export_prefix}/{team_id}/data.native"
        else:
            team_s3_path = f"https://{OBJECT_STORAGE_EXTERNAL_WEB_ANALYTICS_BUCKET}.s3.amazonaws.com/{export_prefix}/{team_id}/data.native"

        export_query = sql_generator(
            date_start="2020-01-01",
            date_end=datetime.now(UTC).strftime("%Y-%m-%d"),
            team_ids=[team_id],
            settings=ch_settings,
            table_name=table_name,
            s3_path=team_s3_path,
        )

        try:
            context.log.info(f"Exporting {table_name} for team {team_id} to: {team_s3_path}")
            sync_execute(export_query)

            successfully_exported_paths.append(team_s3_path)
            context.log.info(f"Successfully exported {table_name} for team {team_id} to: {team_s3_path}")

        except Exception as e:
            context.log.exception(f"Failed to export {table_name} for team {team_id}: {str(e)}")
            failed_team_ids.append(team_id)

    return dagster.Output(
        value=successfully_exported_paths,
        metadata={
            "team_count": len(successfully_exported_paths),
            "exported_paths": successfully_exported_paths,
            "failed_team_ids": failed_team_ids,
        },
    )


@dagster.asset(
    name="web_analytics_stats_export",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_stats_table_daily"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_stats_daily_export(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.Output[list]:
    """
    Exports web_stats_daily data directly to S3 partitioned by team using ClickHouse's native S3 export.
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return export_web_analytics_data_by_team(
        context=context,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_EXPORT_SQL,
        export_prefix="web_stats_daily_export",
        cluster=cluster,
    )


@dagster.asset(
    name="web_analytics_bounces_export",
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_bounces_daily"],
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_bounces_daily_export(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dagster.Output[list]:
    """
    Exports web_bounces_daily data directly to S3 partitioned by team using ClickHouse's native S3 export.
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))
    return export_web_analytics_data_by_team(
        context=context,
        table_name="web_bounces_daily",
        sql_generator=WEB_BOUNCES_EXPORT_SQL,
        export_prefix="web_bounces_daily_export",
        cluster=cluster,
    )


# Daily incremental job with asset-level concurrency control
web_pre_aggregate_daily_job = dagster.define_asset_job(
    name="web_analytics_daily_job",
    selection=["web_analytics_bounces_daily", "web_analytics_stats_table_daily"],
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/max_runtime": str(DAGSTER_WEB_JOB_TIMEOUT),
    },
    executor_def=dagster.multiprocess_executor.configured({"max_concurrent": 1}),
)


@dagster.schedule(
    cron_schedule=HISTORICAL_DAILY_CRON_SCHEDULE,
    job=web_pre_aggregate_daily_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_pre_aggregate_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Runs daily for the previous day's partition.
    The usage of pre-aggregated tables is controlled by a query modifier AND is behind a feature flag.
    """

    # Check for existing runs of the same job to prevent concurrent execution
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason

    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    return dagster.RunRequest(
        partition_key=yesterday,
        run_config={
            "ops": {
                "web_analytics_bounces_daily": {"config": {}},
                "web_analytics_stats_table_daily": {"config": {}},
            }
        },
    )
