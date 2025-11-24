import base64
from contextlib import suppress
from enum import Enum
from typing import Optional

from django.conf import settings

import dagster
import psycopg2
import psycopg2.extras
from clickhouse_driver.errors import Error, ErrorCodes

from posthog.clickhouse import query_tagging
from posthog.clickhouse.cluster import ClickhouseCluster, ExponentialBackoff, RetryPolicy, get_cluster
from posthog.clickhouse.custom_metrics import MetricsClient
from posthog.clickhouse.query_tagging import DagsterTags
from posthog.redis import get_client, redis


class JobOwners(str, Enum):
    TEAM_ANALYTICS_PLATFORM = "team-analytics-platform"
    TEAM_CLICKHOUSE = "team-clickhouse"
    TEAM_DATA_WAREHOUSE = "team-data-warehouse"
    TEAM_ERROR_TRACKING = "team-error-tracking"
    TEAM_EXPERIMENTS = "team-experiments"
    TEAM_GROWTH = "team-growth"
    TEAM_INGESTION = "team-ingestion"
    TEAM_LLMA = "team-llma"
    TEAM_MAX_AI = "team-max-ai"
    TEAM_REVENUE_ANALYTICS = "team-revenue-analytics"
    TEAM_WEB_ANALYTICS = "team-web-analytics"


class ClickhouseClusterResource(dagster.ConfigurableResource):
    """
    The ClickHouse cluster used to run the job.
    """

    client_settings: dict[str, str] = {
        "lightweight_deletes_sync": "0",
        "max_execution_time": "0",
        "max_memory_usage": "0",
        "mutations_sync": "0",
        "receive_timeout": f"{15 * 60}",  # some synchronous queries like dictionary checksumming can be very slow to return
    }

    def create_resource(self, context: dagster.InitResourceContext) -> ClickhouseCluster:
        return get_cluster(
            context.log,
            client_settings=self.client_settings,
            retry_policy=RetryPolicy(
                max_attempts=8,
                delay=ExponentialBackoff(20),
                exceptions=lambda e: (
                    isinstance(e, Error)
                    and (
                        (
                            e.code
                            in (  # these are typically transient errors and unrelated to the query being executed
                                ErrorCodes.NETWORK_ERROR,
                                ErrorCodes.TOO_MANY_SIMULTANEOUS_QUERIES,
                                ErrorCodes.NOT_ENOUGH_SPACE,
                                ErrorCodes.SOCKET_TIMEOUT,
                                439,  # CANNOT_SCHEDULE_TASK: "Cannot schedule a task: cannot allocate thread"
                            )
                        )
                        # queries that exceed memory limits can be retried if they were killed due to total server
                        # memory consumption, but we should avoid retrying queries that were killed due to query limits
                        or (e.code == ErrorCodes.MEMORY_LIMIT_EXCEEDED and "Memory limit (total) exceeded" in e.message)
                    )
                ),
            ),
        )


class RedisResource(dagster.ConfigurableResource):
    """
    A Redis resource that can be used to store and retrieve data.
    """

    def create_resource(self, context: dagster.InitResourceContext) -> redis.Redis:
        client = get_client()
        return client


class PostgresResource(dagster.ConfigurableResource):
    """
    A Postgres database connection resource that returns a psycopg2 connection.
    """

    host: str
    port: str = "5432"
    database: str
    user: str
    password: str

    def create_resource(self, context: dagster.InitResourceContext) -> psycopg2.extensions.connection:
        return psycopg2.connect(
            host=self.host,
            port=int(self.port),
            database=self.database,
            user=self.user,
            password=self.password,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )


def report_job_status_metric(
    context: dagster.RunStatusSensorContext, cluster: dagster.ResourceParam[ClickhouseCluster]
) -> None:
    MetricsClient(cluster).increment(
        "dagster_run_status",
        labels={
            "job_name": context.dagster_run.job_name,
            "status": context.dagster_run.status.name,
        },
    ).result()


job_status_metrics_sensors = [
    dagster.run_status_sensor(
        name=f"{report_job_status_metric.__name__}_{status.name}",
        run_status=status,
        default_status=dagster.DefaultSensorStatus.RUNNING,
        monitor_all_code_locations=True,
    )(report_job_status_metric)
    for status in [
        dagster.DagsterRunStatus.STARTED,
        dagster.DagsterRunStatus.SUCCESS,
        dagster.DagsterRunStatus.FAILURE,
        dagster.DagsterRunStatus.CANCELED,
    ]
]


def dagster_tags(
    context: dagster.OpExecutionContext | dagster.AssetCheckExecutionContext | dagster.AssetExecutionContext,
) -> DagsterTags:
    r = context.run
    tags = DagsterTags(
        job_name=r.job_name,
        run_id=r.run_id,
        tags=r.tags,
        root_run_id=r.root_run_id,
        parent_run_id=r.parent_run_id,
        job_snapshot_id=r.job_snapshot_id,
        execution_plan_snapshot_id=r.execution_plan_snapshot_id,
    )

    with suppress(Exception):
        if isinstance(context, dagster.AssetCheckExecutionContext):
            op = context.op_execution_context
            if op and op.op:
                tags.op_name = op.op.name
        elif isinstance(context, dagster.OpExecutionContext):
            if context.op:
                tags.op_name = context.op.name
        elif isinstance(context, dagster.AssetExecutionContext):
            if context.asset_key:
                tags.asset_key = context.asset_key.to_user_string()

    return tags


def settings_with_log_comment(
    context: dagster.OpExecutionContext | dagster.AssetExecutionContext | dagster.AssetCheckExecutionContext,
) -> dict[str, str]:
    qt = query_tagging.get_query_tags()
    qt.with_dagster(dagster_tags(context))
    return {"log_comment": qt.to_json()}


def check_for_concurrent_runs(
    context: dagster.ScheduleEvaluationContext, tags: dict[str, str]
) -> Optional[dagster.SkipReason]:
    # Get the schedule name from the context
    schedule_name = context._schedule_name
    if schedule_name is None:
        context.log.info("Skipping concurrent runs check because schedule name is not available")
        return None

    # Get the schedule definition from the repository to find the associated job
    schedule_def = context.repository_def.get_schedule_def(schedule_name)
    job_name = schedule_def.job_name

    run_records = context.instance.get_run_records(
        dagster.RunsFilter(
            job_name=job_name,
            tags=tags,
            statuses=[
                dagster.DagsterRunStatus.QUEUED,
                dagster.DagsterRunStatus.NOT_STARTED,
                dagster.DagsterRunStatus.STARTING,
                dagster.DagsterRunStatus.STARTED,
            ],
        )
    )

    if len(run_records) > 0:
        context.log.info(f"Skipping {job_name} due to {len(run_records)} active run(s)")
        return dagster.SkipReason(f"Skipping {job_name} run because another run of the same job is already active")

    return None


def metabase_debug_query_url(run_id: str) -> Optional[str]:
    cloud_deployment = getattr(settings, "CLOUD_DEPLOYMENT", None)
    if cloud_deployment == "US":
        return f"https://metabase.prod-us.posthog.dev/question/1671-get-clickhouse-query-log-for-given-dagster-run-id?dagster_run_id={run_id}"
    if cloud_deployment == "EU":
        return f"https://metabase.prod-eu.posthog.dev/question/544-get-clickhouse-query-log-for-given-dagster-run-id?dagster_run_id={run_id}"
    sql = f"""
SELECT
    hostName() as host,
    event_time,
    type,
    exception IS NOT NULL and exception != '' as has_exception,
    query_duration_ms,
    formatReadableSize(memory_usage) as memory_used,
    formatReadableSize(read_bytes) as data_read,
    JSONExtractString(log_comment, 'dagster', 'run_id') AS dagster_run_id,
    JSONExtractString(log_comment, 'dagster', 'job_name') AS dagster_job_name,
    JSONExtractString(log_comment, 'dagster', 'asset_key') AS dagster_asset_key,
    JSONExtractString(log_comment, 'dagster', 'op_name') AS dagster_op_name,
    exception,
    query
FROM clusterAllReplicas('posthog', system.query_log)
WHERE
    dagster_run_id = '{run_id}'
    AND event_date >= today() - 1
ORDER BY event_time DESC;
"""
    return f"http://localhost:8123/play?user=default#{base64.b64encode(sql.encode("utf-8")).decode("utf-8")}"


@dagster.op(
    out=dagster.DynamicOut(list[int]),
    config_schema={
        "team_ids": dagster.Field(
            dagster.Array(dagster.Int),
            default_value=[],
            is_required=False,
            description="Specific team IDs to process. If empty, processes all teams.",
        ),
        "batch_size": dagster.Field(
            dagster.Int,
            default_value=1000,
            is_required=False,
            description="Number of team IDs per batch.",
        ),
    },
)
def get_all_team_ids_op(context: dagster.OpExecutionContext):
    """Fetch all team IDs to process in batches."""
    from posthog.models.team import Team

    override_team_ids = context.op_config["team_ids"]
    batch_size = context.op_config.get("batch_size", 1000)

    if override_team_ids:
        team_ids = override_team_ids
        context.log.info(f"Processing {len(team_ids)} configured teams: {team_ids}")
    else:
        team_ids = list(Team.objects.exclude(id=0).values_list("id", flat=True))
        context.log.info(f"Processing all {len(team_ids)} teams")

    for i in range(0, len(team_ids), batch_size):
        batch = team_ids[i : i + batch_size]
        yield dagster.DynamicOutput(batch, mapping_key=f"batch_{i // batch_size}")
