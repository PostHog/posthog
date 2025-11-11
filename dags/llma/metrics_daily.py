"""
Daily aggregation of LLMA (LLM Analytics) metrics.

Aggregates AI event counts from the events table into a daily metrics table
for efficient querying and cost analysis.
"""

from datetime import UTC, datetime, timedelta

import dagster
from dagster import BackfillPolicy, DailyPartitionsDefinition

from posthog.clickhouse import query_tagging
from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.cluster import ClickhouseCluster

from dags.common import JobOwners, dagster_tags

# Start date for LLMA metrics (when AI events were introduced)
PARTITION_START_DATE = "2025-01-01"

# Partition definition for daily aggregations
partition_def = DailyPartitionsDefinition(start_date=PARTITION_START_DATE)

# Backfill policy: process 14 days (2 weeks) per run
backfill_policy_def = BackfillPolicy.multi_run(max_partitions_per_run=14)

# ClickHouse settings for aggregation queries
LLMA_CLICKHOUSE_SETTINGS = {
    "max_execution_time": "300",  # 5 minutes
}

# AI event types to track
AI_EVENT_TYPES = [
    "$ai_trace",
    "$ai_generation",
    "$ai_span",
    "$ai_embedding",
]


def get_insert_query(date_start: str, date_end: str) -> str:
    """
    Generate SQL to aggregate AI event counts by team and metric type.

    Uses long format: each metric_name is a separate row for easy schema evolution.
    """
    # Generate UNION ALL for each metric type
    metric_queries = []
    for event_type in AI_EVENT_TYPES:
        # Convert event name to metric name (remove $ prefix, add _count suffix)
        metric_name = f"{event_type.lstrip('$')}_count"
        metric_queries.append(f"""
            SELECT
                date(timestamp) as date,
                team_id,
                '{metric_name}' as metric_name,
                count(distinct uuid) as metric_value
            FROM events
            WHERE event = '{event_type}'
              AND timestamp >= toDateTime('{date_start}', 'UTC')
              AND timestamp < toDateTime('{date_end}', 'UTC')
            GROUP BY date, team_id
            HAVING metric_value > 0
        """)

    union_query = "\nUNION ALL\n".join(metric_queries)

    return f"""
        INSERT INTO llma_metrics_daily (date, team_id, metric_name, metric_value)
        {union_query}
    """


@dagster.asset(
    name="llma_metrics_daily",
    group_name="llma",
    partitions_def=partition_def,
    backfill_policy=backfill_policy_def,
    metadata={"table": "llma_metrics_daily"},
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
        # Since we're using long format, delete all metrics for the date range
        delete_query = f"""
            ALTER TABLE llma_metrics_daily
            DELETE WHERE date >= '{date_start}' AND date < '{date_end}'
        """
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
        "dagster/max_runtime": "1800",  # 30 minutes
    },
)


@dagster.schedule(
    cron_schedule="0 6 * * *",  # 6 AM UTC daily
    job=llma_metrics_daily_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_LLMA.value},
)
def llma_metrics_daily_schedule(context: dagster.ScheduleEvaluationContext):
    """
    Runs daily at 6 AM UTC for the previous day's partition.

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
