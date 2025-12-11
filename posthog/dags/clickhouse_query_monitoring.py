import dagster

from posthog.clickhouse.cluster import ClickhouseCluster, Query
from posthog.dags.common import JobOwners

LONG_RUNNING_THRESHOLD_HOURS = 12


@dagster.op
def check_long_running_queries(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    """Check for ClickHouse queries running longer than the threshold."""
    threshold_seconds = LONG_RUNNING_THRESHOLD_HOURS * 3600

    query = Query(
        f"""
        SELECT
            query_id,
            user,
            elapsed,
            substring(query, 1, 200) as query_preview
        FROM system.processes
        WHERE elapsed > {threshold_seconds}
        """
    )

    rows = cluster.any_host(query).result()

    if rows:
        context.log.error(f"Found {len(rows)} queries running for more than {LONG_RUNNING_THRESHOLD_HOURS} hours:")
        for query_id, user, elapsed, query_preview in rows:
            hours = elapsed / 3600
            context.log.error(f"  - query_id={query_id}, user={user}, elapsed={hours:.1f}h, query={query_preview}...")

        raise Exception(
            f"Found {len(rows)} ClickHouse queries running for more than {LONG_RUNNING_THRESHOLD_HOURS} hours"
        )

    context.log.info(f"No queries running longer than {LONG_RUNNING_THRESHOLD_HOURS} hours")


@dagster.job(
    name="clickhouse_long_running_query_check",
    tags={"owner": JobOwners.TEAM_CLICKHOUSE.value},
)
def clickhouse_long_running_query_check():
    """Check for ClickHouse queries that have been running too long."""
    check_long_running_queries()


@dagster.schedule(
    job=clickhouse_long_running_query_check,
    cron_schedule="0 * * * *",  # Every hour on the hour
    execution_timezone="UTC",
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
def clickhouse_long_running_query_check_schedule():
    """Hourly check for long-running ClickHouse queries."""
    return dagster.RunRequest()
