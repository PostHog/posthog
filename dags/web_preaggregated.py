from datetime import datetime, timedelta
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
    format_team_ids,
)
from posthog.clickhouse.cluster import ClickhouseCluster

# The average pageviews volumes we want to process in each batch.
# We want to use the actual pageview volumes instead of splitting by amount of teams.
DEFAULT_PAGEVIEW_VOLUME_PER_BATCH = 1_000_000

WEB_ANALYTICS_DATE_PARTITION_DEFINITION = dagster.WeeklyPartitionsDefinition(
    start_date="2025-01-01",
    fmt="%Y-%m-%d",
    timezone="UTC",
)

WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=[],
        description="List of team IDs to process - leave empty to process all teams :fire:",
    ),
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
    """Create or ensure the preaggregated tables exist."""
    overview_table = "web_overview_daily"
    stats_table = "web_stats_daily"

    def create_tables(client: Client) -> None:
        client.execute(WEB_OVERVIEW_METRICS_DAILY_SQL(table_name=overview_table))
        client.execute(WEB_STATS_DAILY_SQL(table_name=stats_table))
        client.execute(DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())

    cluster.map_all_hosts(create_tables).result()
    return True


def get_team_pageview_volumes(client: Client) -> dict:
    """Get average daily pageview counts for each team over the last 7 days."""
    query = """
    SELECT
        team_id,
        avg(daily_pageviews) AS avg_daily_pageviews
    FROM (
        SELECT
            team_id,
            toDate(timestamp) AS day,
            count() AS daily_pageviews
        FROM events
        WHERE timestamp >= (now() - toIntervalDay(7))
          AND event = '$pageview'
        GROUP BY team_id, day
    ) AS daily_counts
    GROUP BY team_id
    ORDER BY avg_daily_pageviews DESC
    """

    result = client.execute(query)
    result = dict(result)
    return result


def get_batches_per_pageview_volume(teams_with_volumes: dict, target_batch_size: int = 1_000_000) -> list[list[int]]:
    """Create batches of teams based on pageview volume."""
    teams_sorted = sorted(
        ((team_id, volume) for team_id, volume in teams_with_volumes.items()),
        key=lambda x: x[1],
        reverse=True,
    )

    batches = []
    current_batch = []
    current_batch_volume = 0

    for team_id, volume in teams_sorted:
        if current_batch_volume + volume > target_batch_size and current_batch:
            batches.append(current_batch)
            current_batch = [team_id]
            current_batch_volume = volume
        else:
            current_batch.append(team_id)
            current_batch_volume += volume

    if current_batch:
        batches.append(current_batch)

    return batches


def _process_web_analytics_data(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table_name: str,
    sql_generator: Callable,
) -> str:
    """Process web analytics data for the given date."""
    config = context.op_config
    team_ids = config.get("team_ids", [])

    partition_date = context.partition_key
    start_date = datetime.strptime(partition_date, "%Y-%m-%d")
    end_date = start_date + timedelta(days=7)
    start_date_str = start_date.strftime("%Y-%m-%d 00:00:00")
    end_date_str = end_date.strftime("%Y-%m-%d 00:00:00")

    # Get team pageview volume data
    def fetch_pageview_data(client: Client) -> dict:
        return get_team_pageview_volumes(client)

    pageview_volumes = cluster.any_host(fetch_pageview_data).result()
    context.log.info(f"Retrieved pageview volume data for {len(pageview_volumes)} teams")

    if team_ids:
        filtered_pageview_volumes = {team_id: pageview_volumes.get(team_id, 1) for team_id in team_ids}
        context.log.info(f"Filtering to {len(filtered_pageview_volumes)} teams specified in config")
    else:
        filtered_pageview_volumes = pageview_volumes
        context.log.info(f"Processing all {len(filtered_pageview_volumes)} teams with pageview data")

    batches = get_batches_per_pageview_volume(filtered_pageview_volumes)
    context.log.info(f"Created {len(batches)} batches based on pageview volume")

    total_batches = len(batches)

    for batch_idx, batch_teams in enumerate(batches):
        batch_num = batch_idx + 1

        estimated_pageviews = sum(filtered_pageview_volumes.get(team_id, 1) for team_id in batch_teams)

        context.log.info(
            f"Processing batch {batch_num}/{total_batches} with {len(batch_teams)} teams "
            f"(~{int(estimated_pageviews)} avg daily pageviews) for {table_name}"
        )

        # Delete existing data for this batch and partition
        delete_query = f"""
        ALTER TABLE {table_name} DELETE WHERE
        toDate(day_bucket) >= toDate('{partition_date}')
        AND toDate(day_bucket) < toDate('{end_date_str}')
        AND team_id IN ({format_team_ids(team_ids)})
        """

        # Generate insertion SQL
        query = sql_generator(
            date_start=start_date_str,
            date_end=end_date_str,
            team_ids=team_ids,
            settings=config["clickhouse_settings"],
            table_name=table_name,
        )

        # Define the callback to process the batch using the cluster executor
        # Use default arguments to capture the current values of the variables
        def process_batch(client: Client, delete_query=delete_query, query=query):
            client.execute(delete_query)
            client.execute(query)

        try:
            cluster.map_all_hosts(process_batch).result()
            context.log.info(f"Successfully processed batch {batch_num}/{total_batches} for {table_name}")
        except Exception:
            context.log.exception(f"Error processing batch {batch_num}/{total_batches} for {table_name}")
            raise

    context.log.info(f"Completed processing all {len(filtered_pageview_volumes)} teams for {table_name}")
    return partition_date


@dagster.asset(
    partitions_def=WEB_ANALYTICS_DATE_PARTITION_DEFINITION,
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
)
def web_overview_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """Process web overview metrics for all teams on the given date."""
    return _process_web_analytics_data(
        context=context,
        cluster=cluster,
        table_name="web_overview_daily",
        sql_generator=WEB_OVERVIEW_INSERT_SQL,
    )


@dagster.asset(
    partitions_def=WEB_ANALYTICS_DATE_PARTITION_DEFINITION,
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
)
def web_stats_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
):
    """Process web stats for all teams on the given date."""
    return _process_web_analytics_data(
        context=context,
        cluster=cluster,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
    )


@dagster.schedule(
    cron_schedule="0 1 * * *",
    job_name="web_analytics_daily_job",
    execution_timezone="UTC",
)
def web_analytics_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """Schedule daily runs for the previous day."""
    date = (context.scheduled_execution_time.date() - timedelta(days=1)).strftime("%Y-%m-%d")
    return dagster.RunRequest(
        run_key=date,
        asset_selection=[web_overview_daily, web_stats_daily],
        partition_key=date,
    )


defs = Definitions(
    assets=[
        web_analytics_preaggregated_tables,
        web_overview_daily,
        web_stats_daily,
    ],
    resources={"cluster": ClickhouseClusterResource()},
)
