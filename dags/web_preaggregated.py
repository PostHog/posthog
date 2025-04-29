from datetime import datetime, timedelta
import os
from typing import List

import dagster
from dagster import Field, StringSource, IntSource, Array

from clickhouse_driver import Client
from dags.common import JobOwners
from posthog.models.web_preaggregated.sql import (
    WEB_OVERVIEW_METRICS_DAILY_SQL,
    DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL,
    WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
    WEB_OVERVIEW_INSERT_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster

# WEB_ANALYTICS_DAILY_PARTITION_DEFINITION = dagster.TimeWindowPartitionsDefinition(
#     start="2023-01-01",
#     fmt="%Y-%m-%d",
#     timezone="UTC",
# )

# Pre-compute the default team IDs
DEFAULT_TEAM_IDS = [int(id) for id in os.getenv("WEB_ANALYTICS_TEAM_IDS", "2").split(",")]

# Define config schema using Dagster's native config system instead of Pydantic
WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=DEFAULT_TEAM_IDS,
        description="List of team IDs to process",
    ),
    "days_to_backfill": Field(
        int,
        default_value=30,
        description="Number of days to backfill for each run"
    ),
    "timezone": Field(
        str,
        default_value="UTC",
        description="Timezone to use for date calculations"
    ),
    "target_suffix": Field(
        str,
        default_value="",
        description="Optional suffix to append to table names (e.g., for testing)"
    ),
    "clickhouse_settings": Field(
        str,
        default_value="max_execution_time=240, max_bytes_before_external_group_by=21474836480, distributed_aggregation_memory_efficient=1",
        description="ClickHouse execution settings"
    ),
}


@dagster.op
def ensure_tables_exist(
    context: dagster.OpExecutionContext,
    config: dict,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """Creates the web analytics tables if they don't exist."""
    target_suffix = config["target_suffix"]

    # Determine the table names with optional suffix
    overview_table = f"web_overview_daily{target_suffix}"
    stats_table = f"web_stats_daily{target_suffix}"

    # Create base tables - map to all hosts
    def create_tables(client: Client) -> None:
        context.log.info(f"Creating or ensuring {overview_table} exists")
        client.execute(WEB_OVERVIEW_METRICS_DAILY_SQL(table_name=overview_table))

        context.log.info(f"Creating or ensuring {stats_table} exists")
        client.execute(WEB_STATS_DAILY_SQL(table_name=stats_table))

        # Create distributed tables
        context.log.info(f"Creating or ensuring distributed tables exist")
        client.execute(DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())

    # Execute on all hosts
    cluster.map_all_hosts(create_tables).result()

    return {
        "overview_table": overview_table,
        "stats_table": stats_table,
    }


@dagster.asset(
    # partitions_def=WEB_ANALYTICS_DAILY_PARTITION_DEFINITION,
    group_name="web_analytics",
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
)
def web_overview_metrics_daily(
    context: dagster.AssetExecutionContext, cluster: dagster.ResourceParam[ClickhouseCluster]
):
    """Aggregates web overview metrics daily."""
    config = context.op_config
    partition_date = context.partition_key
    target_suffix = config["target_suffix"]

    team_id_list = ", ".join(str(team_id) for team_id in config["team_ids"])

    start_date = datetime.strptime(partition_date, "%Y-%m-%d")
    end_date = start_date + timedelta(days=1)

    start_date_str = start_date.strftime("%Y-%m-%d 00:00:00")
    end_date_str = end_date.strftime("%Y-%m-%d 00:00:00")

    context.log.info(f"Processing overview metrics for {partition_date}, teams: {team_id_list}")

    query = WEB_OVERVIEW_INSERT_SQL(
        date_start=start_date_str,
        date_end=end_date_str,
        team_ids=team_id_list,
        timezone=config["timezone"],
        settings=config["clickhouse_settings"],
        target_suffix=target_suffix,
    )

    def execute_query(client: Client) -> None:
        client.execute(query)

    cluster.any_host(execute_query).result()
    context.log.info(f"Inserted data into web_overview_daily{target_suffix} for {partition_date}")

    return partition_date


@dagster.asset(
    # partitions_def=dagster.TimeWindowPartitionsDefinition(
    #     start="2023-01-01",
    #     end_offset=timedelta(days=-1),
    #     fmt="%Y-%m-%d",
    #     timezone="UTC",
    # ),
    group_name="web_analytics",
    deps=["ensure_tables_exist"],
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
)
def web_stats_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster]
):
    """Aggregates detailed web stats daily."""
    config = context.op_config
    partition_date = context.partition_key

    team_id_list = ", ".join(str(team_id) for team_id in config["team_ids"])

    start_date = datetime.strptime(partition_date, "%Y-%m-%d")
    end_date = start_date + timedelta(days=1)

    start_date_str = start_date.strftime("%Y-%m-%d 00:00:00")
    end_date_str = end_date.strftime("%Y-%m-%d 00:00:00")

    context.log.info(f"Processing data for {partition_date}, teams: {team_id_list}")

    query = WEB_STATS_INSERT_SQL(
        date_start=start_date_str,
        date_end=end_date_str,
        team_ids=team_id_list,
        timezone=config["timezone"],
        settings=config["clickhouse_settings"],
        target_suffix=config["target_suffix"],
    )

    def execute_query(client: Client) -> None:
        client.execute(query)

    cluster.any_host(execute_query).result()
    context.log.info(f"Inserted data into web_stats_daily for {partition_date}")

    return partition_date


@dagster.op(config_schema=WEB_ANALYTICS_CONFIG_SCHEMA)
def backfill_web_analytics_for_period(
    context: dagster.OpExecutionContext, 
    start_date: str, 
    end_date: str
):
    """Backfills web analytics data for a custom time period."""
    config = context.op_config
    team_id_list = ", ".join(str(team_id) for team_id in config["team_ids"])

    context.log.info(f"Backfilling from {start_date} to {end_date} for teams: {team_id_list}")

    # Import ClickhouseCluster here since we're not using resource in this context
    from posthog.clickhouse.cluster import ClickhouseCluster
    cluster = ClickhouseCluster()
    
    # Call with the required parameters
    tables = ensure_tables_exist(context, config, cluster)

    overview_query = WEB_OVERVIEW_INSERT_SQL(
        date_start=start_date,
        date_end=end_date,
        team_ids=team_id_list,
        timezone=config["timezone"],
        settings=config["clickhouse_settings"],
        target_suffix=config["target_suffix"],
    )

    def execute_overview_query(client: Client) -> None:
        client.execute(overview_query)

    cluster.any_host(execute_overview_query).result()
    context.log.info(f"Inserted overview metrics data for period {start_date} to {end_date}")

    stats_query = WEB_STATS_INSERT_SQL(
        date_start=start_date,
        date_end=end_date,
        team_ids=team_id_list,
        timezone=config["timezone"],
        settings=config["clickhouse_settings"],
        target_suffix=config["target_suffix"],
    )

    def execute_stats_query(client: Client) -> None:
        client.execute(stats_query)

    cluster.any_host(execute_stats_query).result()
    context.log.info(f"Inserted web stats data for period {start_date} to {end_date}")

    return {"start_date": start_date, "end_date": end_date}


@dagster.job()
def web_analytics_daily_job():
    """Job to update web analytics aggregated tables for yesterday."""
    ensure_tables_exist()
    web_overview_metrics_daily()
    web_stats_daily()


@dagster.job()
def web_analytics_backfill_job(start_date: str, end_date: str):
    """Job to backfill web analytics data for a custom time period."""
    backfill_web_analytics_for_period(start_date, end_date)


# Schedule definition - run daily at 2 AM UTC
@dagster.schedule(job=web_analytics_daily_job, cron_schedule="0 2 * * *", execution_timezone="UTC")
def web_analytics_daily_schedule(context):
    """Schedule to run web analytics aggregation daily."""
    return {}


# Define resources
@dagster.resource
def clickhouse_cluster_resource():
    """ClickHouse cluster resource for Dagster."""
    return ClickhouseCluster()


# Configuration for all jobs
defs = dagster.Definitions(
    assets=[web_overview_metrics_daily, web_stats_daily],
    jobs=[web_analytics_daily_job, web_analytics_backfill_job],
    schedules=[web_analytics_daily_schedule],
    resources={"cluster": clickhouse_cluster_resource},
)
