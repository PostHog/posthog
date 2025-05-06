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
)
from posthog.clickhouse.cluster import ClickhouseCluster

# We're using 1M pageviews as the desired batch size, this is arbitrary and can be tuned
# but it is a way to split teams by volume instead of grouping them arbitrarily
DEFAULT_PAGEVIEW_VOLUME_PER_BATCH = 1_000_000

WEB_ANALYTICS_DATE_PARTITION_DEFINITION = dagster.WeeklyPartitionsDefinition(
    start_date="2025-01-01",
    fmt="%Y-%m-%d",
    timezone="UTC",
)

WEB_ANALYTICS_CONFIG_SCHEMA = {
    "team_ids": Field(
        Array(int),
        default_value=[],  # Intentionally empty to process all teams but we can use a custom launchpad on dagster to process specific teams while testing
        description="List of team IDs to process - leave empty to process all teams :fire:",
    ),
    "clickhouse_settings": Field(
        str,
        default_value="max_execution_time=240, max_bytes_before_external_group_by=21474836480, distributed_aggregation_memory_efficient=1",
        description="ClickHouse execution settings",
    ),
}


def get_team_pageview_volumes(client: Client) -> dict:
    """Fetches teams pageview volumes from ClickHouse."""
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
    return dict(client.execute(query))


def split_teams_in_batches(
    pageview_volumes: dict, target_batch_size: int = DEFAULT_PAGEVIEW_VOLUME_PER_BATCH
) -> list[list[int]]:
    """Create batches of teams based on their pageview volume."""
    teams_sorted = sorted(pageview_volumes.items(), key=lambda item: item[1], reverse=True)

    batches = []
    current_batch = []
    current_volume = 0

    for team_id, volume in teams_sorted:
        if current_volume + volume > target_batch_size and current_batch:
            batches.append(current_batch)
            current_batch = [team_id]
            current_volume = volume
        else:
            current_batch.append(team_id)
            current_volume += volume

    if current_batch:
        batches.append(current_batch)

    return batches


def _fetch_pageview_data(
    context: dagster.AssetExecutionContext, cluster: dagster.ResourceParam[ClickhouseCluster]
) -> dict:
    """Fetch team pageview volume data from ClickHouse."""

    def fetch_pageview_data(client: Client) -> dict:
        return get_team_pageview_volumes(client)

    pageview_volumes = cluster.any_host(fetch_pageview_data).result()
    context.log.info(f"Retrieved pageview volume data for {len(pageview_volumes)} teams")
    return pageview_volumes


def _filter_and_batch_teams(
    context: dagster.AssetExecutionContext, pageview_volumes: dict, team_ids: list[int]
) -> tuple[dict, list[list[int]]]:
    """Filter teams based on config if any is provided and create batches using the desired pageview volume per batch."""
    if team_ids:
        filtered_pageview_volumes = {team_id: pageview_volumes.get(team_id, 1) for team_id in team_ids}
        context.log.info(f"Filtering to {len(filtered_pageview_volumes)} teams specified in config")
    else:
        filtered_pageview_volumes = pageview_volumes
        context.log.info(f"Processing all {len(filtered_pageview_volumes)} teams with pageview data")

    batches = split_teams_in_batches(filtered_pageview_volumes)
    context.log.info(f"Created {len(batches)} batches based on pageview volume")

    return filtered_pageview_volumes, batches


def _process_single_team(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    team_id: int,
    table_name: str,
    sql_generator: Callable,
    date_info: dict,
    settings: str,
) -> dict:
    """Process a single team. This function is indepondent in the sense that it deletes previous existing data
    so we can safely use to backfill periods and replace the current week data everyday so we can guarantee the data is always up to date.
    """
    start_time = datetime.now()

    # Extract date information
    partition_date = date_info["partition_date"]
    start_date_str = date_info["start_date_str"]
    end_date_str = date_info["end_date_str"]

    # Delete existing data for this team and partition
    delete_query = f"""
    ALTER TABLE {table_name} DELETE WHERE
    toDate(day_bucket) >= toDate('{partition_date}')
    AND toDate(day_bucket) < toDate('{end_date_str}')
    AND team_id = {team_id}
    """

    # Generate insertion SQL for just this team
    insert_query = sql_generator(
        date_start=start_date_str,
        date_end=end_date_str,
        team_ids=[team_id],
        settings=settings,
        table_name=table_name,
    )

    # Function to execute queries on a single host
    def process_team(client: Client, delete_query=delete_query, insert_query=insert_query):
        client.execute(delete_query)

        client.execute(insert_query)

        # Simple count query to get number of inserted rows
        count_query = f"""
        SELECT count() FROM {table_name}
        WHERE team_id = {team_id}
        AND toDate(day_bucket) >= toDate('{partition_date}')
        AND toDate(day_bucket) < toDate('{end_date_str}')
        """

        rows = client.execute(count_query)[0][0]
        return {"rows_inserted": rows}

    try:
        # Execute on all hosts and collect results
        results = cluster.map_all_hosts(process_team).result()

        # Get the total rows (sum from all hosts)
        rows_inserted = sum(host_data.get("rows_inserted", 0) for host_data in results.values())

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        return {"success": True, "team_id": team_id, "rows_inserted": rows_inserted, "duration_seconds": duration}
    except Exception as e:
        context.log.exception(f"Error processing team {team_id} for {table_name}: {str(e)}")
        return {
            "success": False,
            "team_id": team_id,
            "error": str(e),
            "rows_inserted": 0,
            "duration_seconds": (datetime.now() - start_time).total_seconds(),
        }


def _process_batch(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    batch_teams: list[int],
    batch_num: int,
    total_batches: int,
    table_name: str,
    sql_generator: Callable,
    date_info: dict,
    settings: str,
    pageview_volumes: dict,
) -> dict:
    """Process a batch of teams."""
    batch_start_time = datetime.now()

    pageviews = sum(pageview_volumes.get(team_id, 1) for team_id in batch_teams)
    context.log.info(
        f"Processing batch {batch_num}/{total_batches} with {len(batch_teams)} teams "
        f"(~{int(pageviews)} avg daily pageviews) for {table_name}"
    )

    batch_metrics = {
        "successful_teams": 0,
        "failed_teams": 0,
        "total_rows_inserted": 0,
        "total_teams": len(batch_teams),
        "team_results": [],
    }

    # Let's process each team individually since we're already splitting the volume in batches
    # so we should be ok leaving clickhouse to handle the query load
    for team_id in batch_teams:
        result = _process_single_team(
            context=context,
            cluster=cluster,
            team_id=team_id,
            table_name=table_name,
            sql_generator=sql_generator,
            date_info=date_info,
            settings=settings,
        )

        batch_metrics["team_results"].append(result)

        if result["success"]:
            batch_metrics["successful_teams"] += 1
            batch_metrics["total_rows_inserted"] += result["rows_inserted"]
        else:
            batch_metrics["failed_teams"] += 1

    batch_end_time = datetime.now()
    batch_duration = (batch_end_time - batch_start_time).total_seconds()
    batch_metrics["duration_seconds"] = batch_duration

    context.log.info(
        f"Completed batch {batch_num}/{total_batches}: "
        f"{batch_metrics['successful_teams']}/{batch_metrics['total_teams']} teams successful, "
        f"{batch_metrics['total_rows_inserted']} rows inserted in {batch_duration:.2f}s"
    )

    return batch_metrics


def _create_date_info(partition_key: str) -> dict:
    """Create date information for processing."""
    start_date = datetime.strptime(partition_key, "%Y-%m-%d")
    # We're using weekly partitions, so we'll fill 7 days of data for each one
    end_date = start_date + timedelta(days=7)

    return {
        "partition_date": partition_key,
        "start_date": start_date,
        "end_date": end_date,
        "start_date_str": start_date.strftime("%Y-%m-%d 00:00:00"),
        "end_date_str": end_date.strftime("%Y-%m-%d 00:00:00"),
    }


def _summarize_results(
    context: dagster.AssetExecutionContext, batch_results: list[dict], table_name: str, total_duration: float
) -> dict:
    """Summarize batch results and add asset metadata."""

    metrics = {
        "successful_teams": sum(batch["successful_teams"] for batch in batch_results),
        "failed_teams": sum(batch["failed_teams"] for batch in batch_results),
        "total_teams": sum(batch["total_teams"] for batch in batch_results),
        "total_rows_inserted": sum(batch["total_rows_inserted"] for batch in batch_results),
        "duration_seconds": total_duration,
    }

    success_rate = metrics["successful_teams"] / metrics["total_teams"]
    rows_per_second = metrics["total_rows_inserted"] / total_duration

    context.log.info(
        f"Completed processing for {table_name} for partition {context.partition_key}: "
        f"{metrics['successful_teams']}/{metrics['total_teams']} teams successful ({success_rate:.2%}) "
        f"in {total_duration:.2f}s"
    )

    # Add metrics as metadata for the asset
    context.add_output_metadata(
        {
            # Team metrics
            "teams_processed": metrics["total_teams"],
            "teams_succeeded": metrics["successful_teams"],
            "teams_failed": metrics["failed_teams"],
            "success_rate": f"{success_rate:.2%}",
            # Data metrics
            "rows_inserted": metrics["total_rows_inserted"],
            # Timings
            "total_duration": f"{total_duration:.2f}s",
            "rows_per_second": f"{rows_per_second:.1f}",
        }
    )

    return metrics


def pre_aggregate_web_analytics_data(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table_name: str,
    sql_generator: Callable,
) -> dict:
    """Handles the aggregation pipeline for web analytics pre-aggregated tables. It processes the data in batches of teams based on their pageview volume."""
    process_start = datetime.now()

    config = context.op_config
    team_ids = config.get("team_ids", [])
    clickhouse_settings = config["clickhouse_settings"]

    date_info = _create_date_info(context.partition_key)

    # Get team data and create batches
    pageview_volumes = _fetch_pageview_data(context, cluster)
    filtered_volumes, batches = _filter_and_batch_teams(context, pageview_volumes, team_ids)

    batch_results = []
    for batch_idx, batch_teams in enumerate(batches):
        batch_result = _process_batch(
            context=context,
            cluster=cluster,
            batch_teams=batch_teams,
            batch_num=batch_idx + 1,
            total_batches=len(batches),
            table_name=table_name,
            sql_generator=sql_generator,
            date_info=date_info,
            settings=clickhouse_settings,
            pageview_volumes=filtered_volumes,
        )
        batch_results.append(batch_result)

    total_duration = (datetime.now() - process_start).total_seconds()
    metrics = _summarize_results(
        context=context, batch_results=batch_results, table_name=table_name, total_duration=total_duration
    )

    return {
        "partition_date": date_info["partition_date"],
        "metrics": metrics,
        "batch_results": batch_results,
        "duration_seconds": total_duration,
    }


@dagster.asset(
    name="web_analytics_preaggregated_tables",
    group_name="web_analytics",
    key_prefix=["web_analytics"],
    description="Creates the tables needed for web analytics preaggregated data.",
)
def web_analytics_preaggregated_tables(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    """Creates the tables needed for web analytics preaggregated data."""

    def create_tables(client: Client):
        client.execute(WEB_OVERVIEW_METRICS_DAILY_SQL(table_name="web_overview_daily"))
        client.execute(WEB_STATS_DAILY_SQL(table_name="web_stats_daily"))
        client.execute(DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())

    cluster.map_all_hosts(create_tables).result()
    return True


@dagster.asset(
    name="web_analytics_overview_daily",
    group_name="web_analytics",
    key_prefix=["web_analytics"],
    description="Daily aggregated overview metrics for web analytics. This handles the top overview tiles for web analytics wich includes total pageviews, bounce rate, and average session duration.",
    partitions_def=WEB_ANALYTICS_DATE_PARTITION_DEFINITION,
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_overview_daily"},
)
def web_overview_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict:
    return pre_aggregate_web_analytics_data(
        context=context,
        cluster=cluster,
        table_name="web_overview_daily",
        sql_generator=WEB_OVERVIEW_INSERT_SQL,
    )


@dagster.asset(
    name="web_analytics_stats_table_daily",
    group_name="web_analytics",
    key_prefix=["web_analytics"],
    description="Aggregated dimensional data with pageviews and unique user counts. This is used by the breakdown tiles except the path-specific ones.",
    partitions_def=WEB_ANALYTICS_DATE_PARTITION_DEFINITION,
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_stats_daily"},
)
def web_stats_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict:
    return pre_aggregate_web_analytics_data(
        context=context,
        cluster=cluster,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
    )


@dagster.job(name="web_analytics_pre_aggregate_daily_job")
def web_analytics_pre_aggregate_daily_job():
    """Job that processes the daily web analytics data."""

    web_overview_daily()
    web_stats_daily()


@dagster.schedule(
    cron_schedule="0 1 * * *",
    job=web_analytics_pre_aggregate_daily_job,
    execution_timezone="UTC",
)
def web_analytics_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """Schedule that runs the web analytics job daily at 1 AM UTC."""
    date = (context.scheduled_execution_time.date() - timedelta(days=1)).strftime("%Y-%m-%d")
    return dagster.RunRequest(
        run_key=date,
        partition_key=date,
    )


defs = Definitions(
    assets=[
        web_analytics_preaggregated_tables,
        web_overview_daily,
        web_stats_daily,
    ],
    resources={"cluster": ClickhouseClusterResource()},
    jobs=[web_analytics_pre_aggregate_daily_job],
    schedules=[web_analytics_daily_schedule],
)
