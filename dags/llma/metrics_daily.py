"""
Daily aggregation of LLMA (LLM Analytics) metrics.

Aggregates AI event counts from the events table into a daily metrics table
for efficient querying and cost analysis.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import dagster
from dagster import BackfillPolicy, DailyPartitionsDefinition
from jinja2 import Template

from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster

from dags.common import JobOwners, dagster_tags
from dags.llma.config import AI_EVENT_TYPES, config

# Partition definition for daily aggregations
partition_def = DailyPartitionsDefinition(start_date=config.partition_start_date)

# Backfill policy: process N days per run
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=config.max_partitions_per_run)

# ClickHouse settings for aggregation queries
LLMA_CLICKHOUSE_SETTINGS = {
    "max_execution_time": str(config.clickhouse_max_execution_time),
}

# SQL template directory
SQL_DIR = Path(__file__).parent / "sql"

# Load Jinja templates from SQL files
with open(SQL_DIR / "insert_metrics.sql") as f:
    INSERT_QUERY_TEMPLATE = Template(f.read())

with open(SQL_DIR / "delete_metrics.sql") as f:
    DELETE_QUERY_TEMPLATE = Template(f.read())


def get_insert_query(date_start: str, date_end: str) -> str:
    """
    Generate SQL to aggregate AI event counts by team and metric type.

    Uses long format: each metric_name is a separate row for easy schema evolution.
    """
    return INSERT_QUERY_TEMPLATE.render(
        event_types=AI_EVENT_TYPES,
        date_start=date_start,
        date_end=date_end,
    )


def get_delete_query(date_start: str, date_end: str) -> str:
    """Generate SQL to delete existing data for the date range."""
    return DELETE_QUERY_TEMPLATE.render(
        date_start=date_start,
        date_end=date_end,
    )


@dagster.asset(
    name="llma_metrics_daily",
    group_name="llma",
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": config.table_name},
    tags={"owner": JobOwners.TEAM_LLMA.value},
)
def llma_metrics_daily(
    context: dagster.AssetExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """
    Daily aggregation of LLMA metrics.

    Aggregates AI event counts ($ai_trace, $ai_generation, $ai_span, $ai_embedding)
    by team and date into a long-format metrics table for efficient querying.

    Long format allows adding new metrics without schema changes.
    """
    query_tagging.get_query_tags().with_dagster(dagster_tags(context))

    if not context.partition_time_window:
        raise dagster.Failure("This asset should only be run with a partition_time_window")

    start_datetime, end_datetime = context.partition_time_window
    date_start = start_datetime.strftime("%Y-%m-%d")
    date_end = end_datetime.strftime("%Y-%m-%d")

    context.log.info(f"Aggregating LLMA metrics for {date_start} to {date_end}")

    try:
        # Delete existing data for this date range to ensure idempotency
        delete_query = get_delete_query(date_start, date_end)
        context.log.info(f"Deleting existing metrics: {delete_query}")
        sync_execute(delete_query, settings=LLMA_CLICKHOUSE_SETTINGS)

        # Insert aggregated metrics
        insert_query = get_insert_query(date_start, date_end)
        context.log.info(f"Inserting metrics: {insert_query}")
        sync_execute(insert_query, settings=LLMA_CLICKHOUSE_SETTINGS)

        context.log.info(f"Successfully aggregated LLMA metrics for {date_start}")

    except Exception as e:
        raise dagster.Failure(f"Failed to aggregate LLMA metrics: {str(e)}") from e


# Define the job that runs the asset
llma_metrics_daily_job = dagster.define_asset_job(
    name="llma_metrics_daily_job",
    selection=["llma_metrics_daily"],
    tags={
        "owner": JobOwners.TEAM_LLMA.value,
        "dagster/max_runtime": str(config.job_timeout),
    },
)


@dagster.schedule(
    cron_schedule=config.cron_schedule,
    job=llma_metrics_daily_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_LLMA.value},
)
def llma_metrics_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Runs daily for the previous day's partition.

    Schedule configured in dags.llma.config.
    This aggregates AI event metrics from the events table into the
    llma_metrics_daily table for efficient querying.
    """
    # Calculate yesterday's partition
    yesterday = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")

    context.log.info(f"Scheduling LLMA metrics aggregation for {yesterday}")

    return dagster.RunRequest(
        partition_key=yesterday,
        run_config={
            "ops": {
                "llma_metrics_daily": {"config": {}},
            }
        },
    )
