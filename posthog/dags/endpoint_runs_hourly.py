from datetime import UTC, date, datetime, time, timedelta

from django.conf import settings

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.endpoint_runs import (
    REPLACE_SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE_SQL,
    SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE,
    SHARDED_ENDPOINT_RUNS_HOURLY_TABLE,
    SORT_KEY_COLUMNS,
)
from posthog.clickhouse.log_entries import LOG_ENTRIES_TABLE
from posthog.dags.common import JobOwners
from posthog.dags.common.resources import SatelliteClickhouseClusterResource
from posthog.dags.common.staged_daily_rollup import (
    ONE_GIB,
    build_catch_up_schedule,
    build_overdue_sensor,
    day_query_parameters,
    publish_staged_day,
    query_log_source as staged_rollup_query_log_source,
    refuse_to_run_beside_another_rollup,
    rollup_query_settings,
)

from products.endpoints.backend.facade.enums import ENDPOINTS_LOG_SOURCE
from products.web_analytics.dags.web_preaggregated_utils import recreate_staging_table

MAX_EXECUTION_TIME_SECONDS = 30 * 60
MAX_MEMORY_USAGE_BYTES = 8 * ONE_GIB
ROLLUP_NODE_ROLE = NodeRole.AUX
ROLLUP_START_DATE = "2026-11-20"
# The warehouse suggestions workflow reads this table at 08:30 UTC. The last attempt starts at 04:00 and stops
# within MAX_RUNTIME_SECONDS, and the attempts stay clear of the warehouse object reads rollup at 05:00 to 07:00.
ATTEMPT_HOURS_UTC = (2, 3, 4)
CATCH_UP_DAYS = 7
OVERDUE_AFTER_UTC = time(hour=6)
OVERDUE_CHECK_INTERVAL_SECONDS = 60 * 60
CONCURRENCY_TAG = {"endpoint_runs_hourly_backfill_concurrency": "endpoint_runs_hourly_v1"}
MAX_RUNTIME_SECONDS = 60 * 60
# system.query_log keeps 14 days, and a day also reads the hour before it. A rebuild of an older day would
# publish its runs with no ClickHouse cost, and replace the cost that the first build published.
MAX_REBUILD_AGE_DAYS = 12

# A run's queries finish before its log line is written, so a run just after midnight can have queries
# from the previous day.
QUERY_LOG_LOOKBACK = timedelta(hours=1)
QUERY_LOG_COLUMNS = (
    "event_date, event_time, is_initial_query, type, query_duration_ms, read_bytes, ProfileEvents, log_comment"
)

# build_execution_message in products/endpoints/backend/logs.py writes these lines. A rejected request writes
# "Endpoint execution failed · invalid request · <free text>" instead, which these prefixes leave out, so the
# token patterns below never read that free text.
SUCCEEDED_LINE_PREFIX = "Endpoint executed · path="
FAILED_LINE_PREFIX = "Endpoint execution failed · path="


def _token(name: str, value_pattern: str = "[^ ]+") -> str:
    return f"extract(run_message, ' {name}=({value_pattern})')"


RUNS_SQL = f"""
    SELECT
        team_id,
        endpoint_id,
        execution_id,
        toDateTime(run_at, 'UTC') AS run_time,
        startsWith(run_message, '{FAILED_LINE_PREFIX}') AS is_failed,
        {_token("path")} AS execution_type,
        {_token("cache")} AS cache,
        toUInt64OrZero({_token("duration_ms", "[0-9]+")}) AS wait_ms,
        toUInt32OrZero({_token("version", "[0-9]+")}) AS version,
        {_token("access")} AS access,
        {_token("refresh")} AS refresh_mode,
        toUInt64OrZero({_token("variables", "[0-9]+")}) > 0 AS has_variables,
        {_token("limit", "[0-9]+")} != '' AS has_pagination
    FROM (
        -- log_entries is a ReplacingMergeTree, so a redelivered line can still be there twice.
        SELECT
            toInt64(team_id) AS team_id,
            log_source_id AS endpoint_id,
            instance_id AS execution_id,
            min(timestamp) AS run_at,
            argMin(message, timestamp) AS run_message
        FROM {LOG_ENTRIES_TABLE}
        WHERE log_source = '{ENDPOINTS_LOG_SOURCE}'
            AND timestamp >= %(day_start)s AND timestamp < %(day_end)s
            AND (startsWith(message, '{SUCCEEDED_LINE_PREFIX}') OR startsWith(message, '{FAILED_LINE_PREFIX}'))
        GROUP BY team_id, log_source_id, instance_id
    )"""


def query_cost_sql(source: str) -> str:
    return f"""
    SELECT
        JSONExtractInt(log_comment, 'team_id') AS query_team_id,
        JSONExtractString(log_comment, 'endpoint_execution_id') AS query_execution_id,
        count() AS run_ch_queries,
        sum(query_duration_ms) AS run_ch_duration_ms,
        sum(read_bytes) AS run_ch_read_bytes,
        sum(ProfileEvents['OSCPUVirtualTimeMicroseconds']) AS run_ch_cpu_us
    FROM {source}
    WHERE event_date >= toDate(%(query_log_start)s) AND event_date <= %(day)s
        AND event_time >= %(query_log_start)s AND event_time < %(day_end)s
        AND is_initial_query
        AND type IN ('QueryFinish', 'ExceptionWhileProcessing')
        -- Skips the JSON parse for the many queries that no endpoint run tagged.
        AND position(log_comment, '"endpoint_execution_id"') > 0
    GROUP BY query_team_id, query_execution_id
    HAVING query_execution_id != ''"""


AGGREGATE_COLUMNS = (
    "count() AS runs",
    "countIf(cache = 'hit') AS cache_hits",
    "countIf(cache = 'miss') AS cache_misses",
    "countIf(is_failed) AS failed",
    "min(run_time) AS first_run_at",
    "max(run_time) AS last_run_at",
    "groupBitOr(bitShiftLeft(toUInt16(1), intDiv(toMinute(run_time), 5))) AS active_slots",
    "sum(wait_ms) AS wait_ms_sum",
    "sumIf(wait_ms, cache = 'miss') AS miss_wait_ms_sum",
    "quantilesStateIf(0.5, 0.9)(wait_ms, cache = 'miss') AS miss_wait_ms_quantiles",
    "sum(run_ch_queries) AS ch_queries",
    "sum(run_ch_duration_ms) AS ch_duration_ms_sum",
    "sum(run_ch_read_bytes) AS ch_read_bytes_sum",
    "sum(run_ch_cpu_us) AS ch_cpu_us_sum",
    "quantilesStateIf(0.5, 0.9)(run_ch_duration_ms, run_ch_queries > 0) AS ch_duration_ms_quantiles",
    "quantilesStateIf(0.5, 0.9)(run_ch_read_bytes, run_ch_queries > 0) AS ch_read_bytes_quantiles",
)

DIMENSION_COLUMNS = tuple(column for column in SORT_KEY_COLUMNS if column not in ("team_id", "day", "hour"))

daily_partitions = dagster.DailyPartitionsDefinition(start_date=ROLLUP_START_DATE, timezone="UTC")


def query_log_source() -> str:
    return staged_rollup_query_log_source(QUERY_LOG_COLUMNS)


def insert_rollup_sql(source: str) -> str:
    return f"""
INSERT INTO {SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE}
SELECT
    team_id,
    toDate(%(day)s) AS day,
    toStartOfHour(run_time) AS hour,
    {", ".join(DIMENSION_COLUMNS)},
    {", ".join(AGGREGATE_COLUMNS)}
FROM ({RUNS_SQL}) AS endpoint_runs
LEFT JOIN ({query_cost_sql(source)}) AS query_costs
    ON endpoint_runs.team_id = query_costs.query_team_id
    AND endpoint_runs.execution_id = query_costs.query_execution_id
GROUP BY {", ".join(SORT_KEY_COLUMNS)}
"""


COUNT_RUNS_SQL = f"SELECT count() FROM ({RUNS_SQL})"
TRUNCATE_STAGING_SQL = f"TRUNCATE TABLE {SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE}"


def rollup_query_parameters(day: date) -> dict[str, date | datetime | str]:
    parameters = day_query_parameters(day)
    return {**parameters, "query_log_start": datetime.combine(day, time.min) - QUERY_LOG_LOOKBACK}


def refuse_a_day_past_query_log_retention(day: date) -> None:
    oldest_day = datetime.now(UTC).date() - timedelta(days=MAX_REBUILD_AGE_DAYS)
    if day < oldest_day:
        raise dagster.Failure(
            description=f"The query log no longer covers {day}, so a rebuild would publish its runs with no "
            f"ClickHouse cost. Only days from {oldest_day} on can be rebuilt. Nothing was changed."
        )


def insert_rollup_into_staging(context: dagster.OpExecutionContext, cluster: ClickhouseCluster, day: date) -> None:
    def stage_day(client: Client) -> None:
        client.execute(TRUNCATE_STAGING_SQL)
        client.execute(
            insert_rollup_sql(query_log_source()),
            rollup_query_parameters(day),
            settings=rollup_query_settings(context),
        )

    cluster.any_host_by_roles(stage_day, [ROLLUP_NODE_ROLE]).result()


def count_runs(context: dagster.OpExecutionContext, cluster: ClickhouseCluster, day: date) -> int:
    [[runs]] = cluster.any_host_by_roles(
        lambda client: client.execute(
            COUNT_RUNS_SQL, rollup_query_parameters(day), settings=rollup_query_settings(context)
        ),
        [ROLLUP_NODE_ROLE],
    ).result()
    return runs


def publish_day(context: dagster.OpExecutionContext, cluster: ClickhouseCluster, day: date) -> None:
    if publish_staged_day(
        context,
        cluster,
        day,
        table=SHARDED_ENDPOINT_RUNS_HOURLY_TABLE,
        staging_table=SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE,
        node_role=ROLLUP_NODE_ROLE,
    ):
        return
    runs = count_runs(context, cluster, day)
    if runs:
        raise dagster.Failure(
            description=f"The endpoint logs have {runs} runs for {day}, but staging is empty. "
            "The published day was kept. Run the day again."
        )
    # A stack with no endpoint traffic has no runs on most days, so an empty day succeeds. This also means a
    # broken endpoint log pipeline shows here as days without rows, not as a failed run.
    context.log.info(
        f"The endpoint logs have no runs for {day}. Nothing was published, and the published day was kept."
    )


@dagster.op
def rollup_endpoint_runs_for_day(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> None:
    refuse_to_run_beside_another_rollup(context)
    day = date.fromisoformat(context.partition_key)
    refuse_a_day_past_query_log_retention(day)
    context.log.info(f"Rolling up endpoint runs for {day}")

    recreate_staging_table(
        context,
        cluster,
        SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE,
        REPLACE_SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE_SQL,
        node_role=ROLLUP_NODE_ROLE,
    )
    insert_rollup_into_staging(context, cluster, day)
    publish_day(context, cluster, day)


@dagster.job(
    partitions_def=daily_partitions,
    resource_defs={
        "cluster": SatelliteClickhouseClusterResource(
            satellite_cluster=settings.CLICKHOUSE_AUX_CLUSTER,
            max_execution_time=MAX_EXECUTION_TIME_SECONDS,
            max_memory_usage=MAX_MEMORY_USAGE_BYTES,
        )
    },
    tags={"owner": JobOwners.TEAM_DATA_MODELING.value, "dagster/max_runtime": MAX_RUNTIME_SECONDS, **CONCURRENCY_TAG},
)
def endpoint_runs_hourly_job() -> None:
    rollup_endpoint_runs_for_day()


endpoint_runs_hourly_schedule = build_catch_up_schedule(
    endpoint_runs_hourly_job,
    start_date=ROLLUP_START_DATE,
    attempt_hours_utc=ATTEMPT_HOURS_UTC,
    catch_up_days=CATCH_UP_DAYS,
)

endpoint_runs_hourly_overdue_sensor = build_overdue_sensor(
    endpoint_runs_hourly_job,
    name="endpoint_runs_hourly_overdue_sensor",
    owner=JobOwners.TEAM_DATA_MODELING,
    start_date=ROLLUP_START_DATE,
    attempt_hours_utc=ATTEMPT_HOURS_UTC,
    catch_up_days=CATCH_UP_DAYS,
    overdue_after_utc=OVERDUE_AFTER_UTC,
    check_interval_seconds=OVERDUE_CHECK_INTERVAL_SECONDS,
)
