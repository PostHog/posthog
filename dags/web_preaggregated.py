from datetime import datetime, timedelta
from collections.abc import Callable
from dataclasses import dataclass

import dagster
from dagster import Field, Array, Definitions, op, In, Out
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


@dataclass
class BatchExecutionContext:
    cluster: ClickhouseCluster
    table_name: str
    sql_generator: Callable
    start_date_str: str
    end_date_str: str
    partition_date: str
    clickhouse_settings: str


# Core functions that implement the business logic, available for both production and testing


def get_team_pageview_volumes_core(client: Client) -> dict:
    """Core implementation for fetching team pageview volumes from ClickHouse."""
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


def create_team_batches_core(
    pageview_volumes: dict[int, float], target_batch_size: int = DEFAULT_PAGEVIEW_VOLUME_PER_BATCH
) -> list[list[int]]:
    """Core implementation for creating batches of teams based on their pageview volume."""
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


def filter_team_volumes_core(volumes: dict, team_ids: list[int]) -> dict:
    """Core implementation for filtering team volumes based on provided team_ids."""
    if team_ids:
        return {tid: volumes.get(tid, 1) for tid in team_ids}
    return volumes


# Direct function aliases for testing (no Dagster dependency)
get_team_pageview_volumes = get_team_pageview_volumes_core
get_batches_per_pageview_volume = create_team_batches_core


# Dagster ops that wrap the core functions
@op(out=Out(dict), description="Fetch average daily pageviews per team from ClickHouse.")
def fetch_team_pageview_volumes(context, client: Client) -> dict[int, float]:
    """Dagster op that wraps get_team_pageview_volumes_core."""
    result = get_team_pageview_volumes_core(client)
    context.log.info(f"Fetched pageview volumes for {len(result)} teams")
    return result


@op(
    ins={"pageview_volumes": In(dict)},
    out=Out(list),
    description="Split teams into batches based on their pageview volume.",
)
def create_team_batches(
    context, pageview_volumes: dict[int, float], target_batch_size: int = DEFAULT_PAGEVIEW_VOLUME_PER_BATCH
) -> list[list[int]]:
    """Dagster op that wraps create_team_batches_core."""
    batches = create_team_batches_core(pageview_volumes, target_batch_size)
    context.log.info(f"Created {len(batches)} batches")
    return batches


@op(
    ins={"volumes": In(dict), "team_ids": In(list)},
    out=Out(dict),
    description="Filter team volumes based on provided team_ids",
)
def filter_team_volumes(context, volumes: dict[int, float], team_ids: list[int]) -> dict[int, float]:
    """Dagster op that wraps filter_team_volumes_core."""
    filtered = filter_team_volumes_core(volumes, team_ids)
    context.log.info(f"Filtered to {len(filtered)} teams from config")
    return filtered


def _fetch_pageview_volumes(cluster: ClickhouseCluster) -> dict:
    return cluster.any_host(get_team_pageview_volumes_core).result()


def _process_batch(
    context: dagster.AssetExecutionContext,
    batch_idx: int,
    all_batches: list[list[int]],
    team_ids: list[int],
    volumes: dict[int, int],
    exec_ctx: BatchExecutionContext,
):
    est_views = sum(volumes.get(tid, 1) for tid in team_ids)
    context.log.info(
        f"Batch {batch_idx}/{len(all_batches)}: {len(team_ids)} teams (~{int(est_views)} views) for {exec_ctx.table_name}"
    )

    # Track overall batch timing
    batch_start_time = datetime.now()

    delete_sql = f"""
        ALTER TABLE {exec_ctx.table_name} DELETE WHERE
        toDate(day_bucket) >= toDate('{exec_ctx.partition_date}')
        AND toDate(day_bucket) < toDate('{exec_ctx.end_date_str}')
        AND team_id IN ({format_team_ids(team_ids)})
    """
    insert_sql = exec_ctx.sql_generator(
        date_start=exec_ctx.start_date_str,
        date_end=exec_ctx.end_date_str,
        team_ids=team_ids,
        settings=exec_ctx.clickhouse_settings,
        table_name=exec_ctx.table_name,
    )

    # Query metrics dictionary to track data processing stats
    query_metrics = {
        "rows_deleted": 0,
        "rows_inserted": 0,
        "bytes_processed": 0,
        "query_duration_ms": 0,
        "delete_duration_ms": 0,
        "insert_duration_ms": 0,
    }

    def execute(client: Client, delete_query=delete_sql, insert_query=insert_sql):
        # Track rows deleted - with send_progress_in_http_headers to get statistics
        settings = {
            "send_progress_in_http_headers": 1,
            "wait_end_of_query": 1,
            "log_queries": 1,
            "output_format_json_quote_64bit_integers": 0,
            "session_id": f"batch_{batch_idx}_{datetime.now().isoformat()}",
        }

        delete_start_time = datetime.now()
        client.execute(delete_query, settings=settings)
        delete_end_time = datetime.now()
        delete_duration = (delete_end_time - delete_start_time).total_seconds() * 1000
        query_metrics["delete_duration_ms"] = delete_duration

        # For insert, we can get metrics directly from the client result summary
        insert_start_time = datetime.now()
        result, summary = client.execute(
            insert_query,
            settings=settings,
            with_summary=True,  # Get execution summary directly
        )
        insert_end_time = datetime.now()
        insert_duration = (insert_end_time - insert_start_time).total_seconds() * 1000

        # Extract metrics from summary
        if summary:
            query_metrics["rows_inserted"] = summary.get("written_rows", 0)
            query_metrics["bytes_processed"] = summary.get("read_bytes", 0)

        query_metrics["insert_duration_ms"] = insert_duration
        query_metrics["query_duration_ms"] = delete_duration + insert_duration

        return query_metrics

    try:
        metrics_results = exec_ctx.cluster.map_all_hosts(execute).result()

        # Calculate total batch duration including overhead
        batch_end_time = datetime.now()
        batch_duration_ms = (batch_end_time - batch_start_time).total_seconds() * 1000

        # Aggregate metrics across all hosts
        batch_metrics = {
            "rows_deleted": 0,
            "rows_inserted": 0,
            "bytes_processed": 0,
            "query_duration_ms": 0,
            "delete_duration_ms": 0,
            "insert_duration_ms": 0,
            "batch_duration_ms": batch_duration_ms,  # Total batch time including overhead
        }

        for host_metrics in metrics_results.values():
            batch_metrics["rows_deleted"] += host_metrics.get("rows_deleted", 0)
            batch_metrics["rows_inserted"] += host_metrics.get("rows_inserted", 0)
            batch_metrics["bytes_processed"] += host_metrics.get("bytes_processed", 0)
            batch_metrics["query_duration_ms"] += host_metrics.get("query_duration_ms", 0)
            batch_metrics["delete_duration_ms"] += host_metrics.get("delete_duration_ms", 0)
            batch_metrics["insert_duration_ms"] += host_metrics.get("insert_duration_ms", 0)

        # Calculate efficiency metrics
        overhead_ms = batch_duration_ms - batch_metrics["query_duration_ms"]
        efficiency = (batch_metrics["query_duration_ms"] / batch_duration_ms) * 100 if batch_duration_ms > 0 else 0

        context.log.info(
            f"Batch {batch_idx} metrics: "
            f"{batch_metrics['rows_inserted']} rows inserted, "
            f"{batch_metrics['bytes_processed'] / (1024*1024):.2f} MB processed"
        )

        context.log.info(
            f"Batch {batch_idx} timing: "
            f"Total: {batch_metrics['batch_duration_ms']:.2f}ms "
            f"(Delete: {batch_metrics['delete_duration_ms']:.2f}ms, "
            f"Insert: {batch_metrics['insert_duration_ms']:.2f}ms, "
            f"Overhead: {overhead_ms:.2f}ms, "
            f"Efficiency: {efficiency:.1f}%)"
        )

        context.log.info(f"Successfully processed batch {batch_idx} for {exec_ctx.table_name}")
        return True, len(team_ids), batch_metrics
    except Exception as e:
        context.log.exception(f"Error in batch {batch_idx} for {exec_ctx.table_name}: {str(e)}")
        # Don't raise the exception, just return failure status
        return False, len(team_ids), {}


def _execute_batches(
    context: dagster.AssetExecutionContext,
    batches: list[list[int]],
    volumes: dict[int, int],
    exec_context: BatchExecutionContext,
):
    # Track overall execution time
    execution_start = datetime.now()

    total_teams = sum(len(batch) for batch in batches)
    successful_teams = 0
    failed_teams = 0
    successful_batches = 0
    failed_batches = 0

    # Aggregate metrics across all batches
    total_metrics = {
        "rows_deleted": 0,
        "rows_inserted": 0,
        "bytes_processed": 0,
        "query_duration_ms": 0,
        "delete_duration_ms": 0,
        "insert_duration_ms": 0,
        "batch_duration_ms": 0,
    }

    for idx, team_ids in enumerate(batches, 1):
        success, team_count, batch_metrics = _process_batch(context, idx, batches, team_ids, volumes, exec_context)
        if success:
            successful_teams += team_count
            successful_batches += 1

            # Add batch metrics to totals
            for metric_key, metric_value in batch_metrics.items():
                if metric_key in total_metrics:
                    total_metrics[metric_key] += metric_value
        else:
            failed_teams += team_count
            failed_batches += 1

    # Calculate overall execution time including all overhead
    execution_end = datetime.now()
    total_execution_seconds = (execution_end - execution_start).total_seconds()

    # Calculate data size in human-readable format
    data_size_mb = total_metrics["bytes_processed"] / (1024 * 1024)
    data_size_str = f"{data_size_mb:.2f} MB"
    if data_size_mb > 1024:
        data_size_str = f"{data_size_mb / 1024:.2f} GB"

    # Calculate timing breakdown and efficiency
    query_seconds = total_metrics["query_duration_ms"] / 1000
    delete_seconds = total_metrics["delete_duration_ms"] / 1000
    insert_seconds = total_metrics["insert_duration_ms"] / 1000
    overhead_seconds = total_execution_seconds - query_seconds
    efficiency = (query_seconds / total_execution_seconds) * 100 if total_execution_seconds > 0 else 0

    # Log summary
    success_rate = successful_teams / total_teams if total_teams > 0 else 1.0
    context.log.info(
        f"Batch execution summary: {successful_batches}/{len(batches)} batches succeeded "
        f"({successful_teams}/{total_teams} teams, {success_rate:.2%} success rate)"
    )

    context.log.info(
        f"Data processing metrics: " f"{total_metrics['rows_inserted']} rows inserted, " f"{data_size_str} processed"
    )

    context.log.info(
        f"Timing breakdown: "
        f"Total: {total_execution_seconds:.2f}s "
        f"(Queries: {query_seconds:.2f}s [{efficiency:.1f}%], "
        f"Delete: {delete_seconds:.2f}s, "
        f"Insert: {insert_seconds:.2f}s, "
        f"Overhead: {overhead_seconds:.2f}s)"
    )

    # Calculate throughput metrics
    rows_per_second = total_metrics["rows_inserted"] / total_execution_seconds if total_execution_seconds > 0 else 0
    mb_per_second = data_size_mb / total_execution_seconds if total_execution_seconds > 0 else 0

    context.log.info(f"Performance: " f"{rows_per_second:.1f} rows/sec, " f"{mb_per_second:.2f} MB/sec")

    return {
        "total_teams": total_teams,
        "successful_teams": successful_teams,
        "failed_teams": failed_teams,
        "success_rate": success_rate,
        "successful_batches": successful_batches,
        "failed_batches": failed_batches,
        "data_metrics": {
            "rows_inserted": total_metrics["rows_inserted"],
            "rows_deleted": total_metrics["rows_deleted"],
            "bytes_processed": total_metrics["bytes_processed"],
            "data_size_human": data_size_str,
        },
        "timing_metrics": {
            "total_seconds": total_execution_seconds,
            "query_seconds": query_seconds,
            "delete_seconds": delete_seconds,
            "insert_seconds": insert_seconds,
            "overhead_seconds": overhead_seconds,
            "efficiency_percent": efficiency,
        },
        "performance_metrics": {
            "rows_per_second": rows_per_second,
            "mb_per_second": mb_per_second,
        },
    }


def _process_web_analytics_data(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
    table_name: str,
    sql_generator: Callable,
) -> dict:
    # Track overall processing time
    process_start = datetime.now()

    config = context.op_config
    team_ids = config.get("team_ids", [])
    partition_date = context.partition_key
    start_dt = datetime.strptime(partition_date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=7)

    exec_ctx = BatchExecutionContext(
        cluster=cluster,
        table_name=table_name,
        sql_generator=sql_generator,
        start_date_str=start_dt.strftime("%Y-%m-%d 00:00:00"),
        end_date_str=end_dt.strftime("%Y-%m-%d 00:00:00"),
        partition_date=partition_date,
        clickhouse_settings=config["clickhouse_settings"],
    )

    volumes = _fetch_pageview_volumes(cluster)
    filtered_volumes = filter_team_volumes_core(volumes, team_ids)
    batches = create_team_batches_core(filtered_volumes)

    context.log.info(f"Starting processing for {table_name}: {len(filtered_volumes)} teams in {len(batches)} batches")

    results = _execute_batches(context, batches, filtered_volumes, exec_ctx)

    # Calculate total processing time including all overhead
    process_end = datetime.now()
    total_process_seconds = (process_end - process_start).total_seconds()
    setup_seconds = total_process_seconds - results["timing_metrics"]["total_seconds"]

    context.log.info(
        f"Completed processing for {table_name}: {results['successful_teams']}/{results['total_teams']} teams successful"
    )

    context.log.info(
        f"Total process time: {total_process_seconds:.2f}s "
        f"(Setup: {setup_seconds:.2f}s, Execution: {results['timing_metrics']['total_seconds']:.2f}s)"
    )

    # Add detailed metrics as metadata for the asset
    context.add_output_metadata(
        {
            # Team metrics
            "teams_processed": results["total_teams"],
            "teams_succeeded": results["successful_teams"],
            "teams_failed": results["failed_teams"],
            "success_rate": f"{results['success_rate']:.2%}",
            "successful_batches": results["successful_batches"],
            "failed_batches": results["failed_batches"],
            # Data metrics
            "rows_inserted": results["data_metrics"]["rows_inserted"],
            "rows_deleted": results["data_metrics"]["rows_deleted"],
            "data_processed": results["data_metrics"]["data_size_human"],
            "bytes_processed": results["data_metrics"]["bytes_processed"],
            "compression_ratio": f"{results['data_metrics']['rows_inserted'] / (results['data_metrics']['bytes_processed'] / 1024) if results['data_metrics']['bytes_processed'] > 0 else 0:.2f} rows/KB",
            # Timing metrics
            "total_duration": f"{total_process_seconds:.2f}s",
            "execution_duration": f"{results['timing_metrics']['total_seconds']:.2f}s",
            "setup_duration": f"{setup_seconds:.2f}s",
            "query_duration": f"{results['timing_metrics']['query_seconds']:.2f}s",
            "delete_duration": f"{results['timing_metrics']['delete_seconds']:.2f}s",
            "insert_duration": f"{results['timing_metrics']['insert_seconds']:.2f}s",
            "overhead_duration": f"{results['timing_metrics']['overhead_seconds']:.2f}s",
            "efficiency": f"{results['timing_metrics']['efficiency_percent']:.1f}%",
            # Resource metrics
            "memory_usage": f"{results['performance_metrics']['mb_per_second']:.2f}MB/s",
            "cpu_time": f"{results['timing_metrics']['total_seconds']:.2f}s",
            # Performance indicators
            "rows_per_second": f"{results['performance_metrics']['rows_per_second']:.1f}",
            "mb_per_second": f"{results['performance_metrics']['mb_per_second']:.2f}",
        }
    )

    # Return a structured result with both the partition date and processing results
    return {
        "partition_date": partition_date,
        "processing_results": results,
    }


@dagster.asset(
    name="preaggregated_tables",
    group_name="web_analytics",
    description="Creates the tables needed for web analytics preaggregated data.",
)
def web_analytics_preaggregated_tables(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> bool:
    def create_tables(client: Client):
        client.execute(WEB_OVERVIEW_METRICS_DAILY_SQL(table_name="web_overview_daily"))
        client.execute(WEB_STATS_DAILY_SQL(table_name="web_stats_daily"))
        client.execute(DISTRIBUTED_WEB_OVERVIEW_METRICS_DAILY_SQL())
        client.execute(DISTRIBUTED_WEB_STATS_DAILY_SQL())

    cluster.map_all_hosts(create_tables).result()
    return True


@dagster.asset(
    name="overview_daily",
    group_name="web_analytics",
    key_prefix=["web", "metrics"],
    description="Daily aggregated overview metrics for web analytics across all teams.",
    partitions_def=WEB_ANALYTICS_DATE_PARTITION_DEFINITION,
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_overview_daily", "data_type": "metrics", "refresh_frequency": "daily"},
)
def web_overview_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict:
    return _process_web_analytics_data(
        context=context,
        cluster=cluster,
        table_name="web_overview_daily",
        sql_generator=WEB_OVERVIEW_INSERT_SQL,
    )


@dagster.asset(
    name="stats_daily",
    group_name="web_analytics",
    key_prefix=["web", "stats"],
    description="Daily detailed statistics for web analytics across all teams.",
    partitions_def=WEB_ANALYTICS_DATE_PARTITION_DEFINITION,
    config_schema=WEB_ANALYTICS_CONFIG_SCHEMA,
    deps=["web_analytics_preaggregated_tables"],
    metadata={"table": "web_stats_daily", "data_type": "statistics", "refresh_frequency": "daily"},
)
def web_stats_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> dict:
    return _process_web_analytics_data(
        context=context,
        cluster=cluster,
        table_name="web_stats_daily",
        sql_generator=WEB_STATS_INSERT_SQL,
    )


# Optional: Create a lineage asset that depends on both daily assets
# This can be used to track overall web analytics processing status
@dagster.asset(
    name="daily_processing_status",
    group_name="web_analytics",
    key_prefix=["web", "status"],
    description="Overall status of daily web analytics processing.",
    partitions_def=WEB_ANALYTICS_DATE_PARTITION_DEFINITION,
    deps=[["web", "metrics", "overview_daily"], ["web", "stats", "stats_daily"]],
)
def web_analytics_daily_status(
    context: dagster.AssetExecutionContext,
    overview_daily: dict,
    stats_daily: dict,
) -> dict:
    """Asset that tracks the overall status of web analytics daily processing."""
    # Calculate combined metrics
    overview_results = overview_daily["processing_results"]
    stats_results = stats_daily["processing_results"]

    total_teams = overview_results["total_teams"] + stats_results["total_teams"]
    successful_teams = overview_results["successful_teams"] + stats_results["successful_teams"]
    failed_teams = overview_results["failed_teams"] + stats_results["failed_teams"]

    # Only consider success if both are above the threshold
    overview_success = overview_results["success_rate"] > 0.8
    stats_success = stats_results["success_rate"] > 0.8
    overall_success = overview_success and stats_success

    results = {
        "partition_date": context.partition_key,
        "overall_success": overall_success,
        "overview_success_rate": overview_results["success_rate"],
        "stats_success_rate": stats_results["success_rate"],
        "total_teams_processed": total_teams,
        "total_teams_succeeded": successful_teams,
        "total_teams_failed": failed_teams,
    }

    # Add overall status metadata
    context.add_output_metadata(
        {
            "overall_success": "✅ Successful" if overall_success else "❌ Has failures",
            "overview_success_rate": f"{overview_results['success_rate']:.2%}",
            "stats_success_rate": f"{stats_results['success_rate']:.2%}",
            "total_teams_processed": total_teams,
            "total_teams_failed": failed_teams,
        }
    )

    return results


# Define a job that selects the web analytics assets
@dagster.job(name="web_analytics_daily_job")
def web_analytics_daily_job():
    """Job that processes the daily web analytics data."""
    # The job can reference the assets directly
    web_overview_daily()
    web_stats_daily()


@dagster.schedule(
    cron_schedule="0 1 * * *",
    job=web_analytics_daily_job,
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
        web_analytics_daily_status,
    ],
    resources={"cluster": ClickhouseClusterResource()},
    jobs=[web_analytics_daily_job],
    schedules=[web_analytics_daily_schedule],
)
