from datetime import timedelta

import dagster
from clickhouse_driver import Client

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.cluster import ClickhouseCluster
from posthog.clickhouse.query_tagging import Feature
from posthog.dags.common import JobOwners, settings_with_log_comment
from posthog.dags.common.resources import OpsClickhouseClusterResource

from products.data_modeling.backend.facade.api import record_job_bytes_read

SOURCE_TABLE = "posthog.query_log_archive"
SOURCE_NODE_ROLE = NodeRole.OPS
MATERIALIZE_ACTIVITY_TYPE = "materialize_view_activity"
# Each run looks back this far, so a job is still matched when earlier runs failed or the
# job finished late in a long materialization.
LOOKBACK = timedelta(hours=24)
MAX_EXECUTION_TIME_SECONDS = 10 * 60
MAX_MEMORY_USAGE_BYTES = 4 * 1024**3

hourly_partitions = dagster.HourlyPartitionsDefinition(start_date="2026-10-01-00:00", timezone="UTC")

# One materialize activity runs every ClickHouse query of one job, and the Temporal run id names
# that activity's workflow run, which is also the job's ``workflow_run_id``. ``read_bytes`` on an
# initial query already includes what the distributed leaves read. Failed queries count because the
# cluster still did the reads.
BYTES_READ_BY_WORKFLOW_RUN_SQL = f"""
SELECT lc_temporal__workflow_run_id, sum(read_bytes)
FROM {{source_table}}
WHERE initial_query_start_time >= %(window_start)s
    AND initial_query_start_time < %(window_end)s
    AND lc_feature = '{Feature.DATA_MODELING.value}'
    AND lc_temporal__activity_type = '{MATERIALIZE_ACTIVITY_TYPE}'
    AND lc_temporal__workflow_run_id != ''
    AND is_initial_query
    AND type != 'QueryStart'
GROUP BY lc_temporal__workflow_run_id
"""


@dagster.op
def record_clickhouse_job_bytes_read(
    context: dagster.OpExecutionContext,
    cluster: dagster.ResourceParam[ClickhouseCluster],
) -> int:
    """Copy the ClickHouse bytes read by each data modeling job from the query log archive onto the job."""
    window = context.partition_time_window
    window_start = window.start - LOOKBACK + (window.end - window.start)
    query = BYTES_READ_BY_WORKFLOW_RUN_SQL.format(source_table=SOURCE_TABLE)

    def read(client: Client) -> list[tuple[str, int]]:
        return client.execute(
            query,
            {"window_start": window_start, "window_end": window.end},
            settings=settings_with_log_comment(context),
        )

    rows = cluster.any_host_by_role(read, SOURCE_NODE_ROLE).result()
    written = record_job_bytes_read(dict(rows), finished_before=window.end)
    context.log.info(f"Matched {len(rows)} workflow runs from {window_start} to {window.end}, wrote {written} jobs")
    context.add_output_metadata({"workflow_runs": len(rows), "jobs_written": written})
    return written


@dagster.job(
    partitions_def=hourly_partitions,
    resource_defs={
        "cluster": OpsClickhouseClusterResource(
            max_execution_time=MAX_EXECUTION_TIME_SECONDS,
            max_memory_usage=MAX_MEMORY_USAGE_BYTES,
        )
    },
    tags={"owner": JobOwners.TEAM_DATA_MODELING.value},
)
def data_modeling_job_bytes_read_job() -> None:
    record_clickhouse_job_bytes_read()


data_modeling_job_bytes_read_schedule = dagster.build_schedule_from_partitioned_job(
    data_modeling_job_bytes_read_job,
    minute_of_hour=20,
    default_status=dagster.DefaultScheduleStatus.RUNNING,
)
