from datetime import datetime, timedelta
import os
from typing import Optional
from collections.abc import Callable

import dagster
from dagster import Field, Array, Definitions

from clickhouse_driver import Client
from dags.common import ClickhouseClusterResource
from posthog.models.web_preaggregated.sql import (
    WEB_OVERVIEW_METRICS_DAILY_SQL,
    DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL,
    WEB_STATS_DAILY_SQL,
    DISTRIBUTED_WEB_STATS_DAILY_SQL,
    WEB_OVERVIEW_INSERT_SQL,
    WEB_STATS_INSERT_SQL,
)
from posthog.clickhouse.cluster import ClickhouseCluster

WEB_ANALYTICS_DAILY_PARTITION_DEFINITION = dagster.WeeklyPartitionsDefinition(
    start_date="2025-01-01",
    fmt="%Y-%m-%d",
    timezone="UTC",
)

DEFAULT_TEAM_IDS = [int(id) for id in os.getenv("WEB_ANALYTICS_TEAM_IDS", "").split(",") if id]

WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=DEFAULT_TEAM_IDS,
        description="List of team IDs to process - leave empty to process all teams :fire:",
    ),
    "timezone": Field(str, default_value="UTC", description="Timezone to use for date calculations"),
    "clickhouse_settings": Field(
        str,
        default_value="max_execution_time=240, max_bytes_before_external_group_by=21474836480, distributed_aggregation_memory_efficient=1",
        description="ClickHouse execution settings",
    ),
}


@dagster.asset
def web_analytics_preaggregated_tables(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    overview_table = f"web_overview_daily"
    stats_table = f"web_stats_table_daily"

    def create_tables(client: Client) -> None:
        context.log.info(f"Creating or ensuring {overview_table} exists")
        client.execute(WEB_OVERVIEW_METRICS_DAILY_SQL(table_name=overview_table))

        context.log.info(f"Creating or ensuring {stats_table} exists")
        client.execute(WEB_STATS_DAILY_SQL(table_name=stats_table))

        context.log.info(f"Creating or ensuring distributed tables exist")
        client.execute(DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())

    cluster.map_all_hosts(create_tables).result()

    return True


# Not being used so far. Let's test the materialization of the assets first
def get_active_teams(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> list[int]:
    """Determine active teams for web analytics processing."""

    # Querying clickhouse for teams that have web analytics events in the period
    # this is used to only process teams that still have events in the period.
    # If this proves too slow, we can query postgres directly.
    def fetch_active_teams(client: Client) -> list:
        query = """
        SELECT DISTINCT team_id
        FROM events
        WHERE event IN ('$pageview', '$screen')
          AND timestamp >= '2025-01-01 00:00:00'
        ORDER BY team_id
        """
        result = client.execute(query)
        return [row[0] for row in result]

    active_teams = cluster.any_host(fetch_active_teams).result()

    for team_id in active_teams:
        context.instance.add_dynamic_partitions("teams", [str(team_id)])

    return active_teams


def _process_web_analytics_data(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    partition_date: str,
    team_partition: Optional[str],
    table_name: str,
    sql_generator: Callable,
    team_id: Optional[int] = None,
) -> str:
    """Common function to process web analytics data for both overview and stats tables."""
    config = context.op_config

    if team_id is not None:
        team_id_list = str(team_id)
        log_teams = f"team {team_id}"
    elif team_partition is not None and team_partition != "all":
        team_id_list = team_partition
        log_teams = f"team {team_partition}"
    else:
        team_id_list = ", ".join(str(team_id) for team_id in config["team_ids"]) if config["team_ids"] else ""
        log_teams = team_id_list or "ALL TEAMS"

    start_date = datetime.strptime(partition_date, "%Y-%m-%d")
    end_date = datetime.now() + timedelta(days=1)

    start_date_str = start_date.strftime("%Y-%m-%d 00:00:00")
    end_date_str = end_date.strftime("%Y-%m-%d 00:00:00")

    context.log.info(f"Processing data for {table_name}, date: {partition_date}, teams: {log_teams}")

    query = sql_generator(
        date_start=start_date_str,
        date_end=end_date_str,
        team_ids=team_id_list,
        timezone=config["timezone"],
        settings=config["clickhouse_settings"],
    )

    # Log the query for debugging
    context.log.debug(query)

    def execute_query(client: Client) -> None:
        try:
            client.execute(query)
        except Exception as e:
            context.log.info(f"\n\nERROR EXECUTING {table_name.upper()} QUERY: {str(e)}\n\n")
            context.log.exception(f"Error executing query: {str(e)}")
            raise

    try:
        cluster.any_host(execute_query).result()
        context.log.info(f"Inserted data into {table_name} for {partition_date}")
    except Exception as e:
        context.log.info(f"\n\nERROR IN {table_name.upper()}: {str(e)}\n\n")
        context.log.exception(f"Error in {table_name}: {str(e)}")
        raise

    return team_id if team_id is not None else partition_date


def _handle_partition_key(partition_key: str | dict) -> tuple[str, Optional[str]]:
    if isinstance(partition_key, dict):
        partition_date = partition_key["date"]
        team_partition = partition_key.get("team")
    else:
        partition_date = partition_key
        team_partition = None

    return partition_date, team_partition


@dagster.asset(
    partitions_def=WEB_ANALYTICS_DAILY_PARTITION_DEFINITION,
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
)
def web_overview_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """Aggregates the summarized metrics including pageviews, users, bounce rate, and session duration for the top overview tiles on Web Analytics. Used by the WebOverviewQueryRunner."""

    partition_date, team_partition = _handle_partition_key(context.partition_key)

    return _process_web_analytics_data(
        context=context,
        cluster=cluster,
        partition_date=partition_date,
        team_partition=team_partition,
        table_name="web_overview_daily",
        sql_generator=WEB_OVERVIEW_INSERT_SQL,
    )


@dagster.asset(
    partitions_def=WEB_ANALYTICS_DAILY_PARTITION_DEFINITION,
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
)
def web_stats_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """Aggregates detailed dimensional data used by the WebStatsTableQueryRunner and are used for the web analytics breakdown tables."""
    partition_date, team_partition = _handle_partition_key(context.partition_key)

    return _process_web_analytics_data(
        context=context,
        cluster=cluster,
        partition_date=partition_date,
        team_partition=team_partition,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
    )


defs = Definitions(
    assets=[
        web_analytics_preaggregated_tables,
        web_overview_daily,
        web_stats_daily,
    ],
    resources={"cluster": ClickhouseClusterResource()},
)
