# Engineering analytics CI precompute: parsed workflow run rows and job attempt rows, stored out of the
# S3-backed warehouse tables into native ClickHouse. One lazy job stores the rows that one repository
# of one warehouse source created on one day.
#
# A row is identified by (source_id, ci_engine, id), and a job row also by run_attempt, because a
# Depot CI job attempt is listed under each later attempt of its run.

from django.conf import settings

from posthog.clickhouse.table_engines import Distributed, ReplacingMergeTree

CI_RUNS_TABLE_BASE_NAME = "engineering_analytics_ci_runs_precomputed"
CI_JOBS_TABLE_BASE_NAME = "engineering_analytics_ci_jobs_precomputed"

SHARDING_KEY = "cityHash64(source_id)"

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {{table_name}}
(
    team_id Int64,
    job_id UUID,

    source_id String,
    repository String,
    ci_engine LowCardinality(String),
{columns}
    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = {{engine}}
"""

CI_RUNS_TABLE_BASE_SQL = _TABLE_SQL.format(
    columns="""
    id Int64,
    workflow_name Nullable(String),
    head_sha Nullable(String),
    head_branch Nullable(String),
    status Nullable(String),
    conclusion Nullable(String),
    run_started_at Nullable(DateTime64(6, 'UTC')),
    run_started_at_raw String,
    updated_at Nullable(DateTime64(6, 'UTC')),
    created_at Nullable(DateTime64(6, 'UTC')),
    run_attempt Nullable(Int64),
    is_merge_queue UInt8,
    pr_number Int64,
    commit_pr_number Nullable(Int64),
    duration_seconds Nullable(Int64),
    repo_owner String,
    repo_name String,
    native_run_id Nullable(String),
    native_workflow_run_id Nullable(String),
    is_handoff_shell UInt8,
"""
)

CI_JOBS_TABLE_BASE_SQL = _TABLE_SQL.format(
    columns="""
    id Int64,
    run_id Int64,
    run_attempt Int64,
    name String,
    workflow_name String,
    head_sha String,
    head_branch String,
    status String,
    conclusion Nullable(String),
    labels String,
    runner_name String,
    created_at Nullable(DateTime64(6, 'UTC')),
    created_at_raw String,
    started_at Nullable(DateTime64(6, 'UTC')),
    completed_at Nullable(DateTime64(6, 'UTC')),
    duration_seconds Nullable(Int64),
    queue_seconds Nullable(Int64),
    provisioning_seconds Nullable(Int64),
    is_rerun_copy UInt8,
    native_run_id Nullable(String),
    native_workflow_run_id Nullable(String),
    native_job_id Nullable(String),
    native_attempt_id Nullable(String),
    provider Nullable(String),
    os Nullable(String),
    vcpu Nullable(Int64),
    multiplier Nullable(Int64),
    billable_seconds Nullable(Int64),
    estimated_cost_usd Nullable(Float64),
"""
)

_SHARDED_TABLE_SUFFIX_SQL = """
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY ({order_by})
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1
"""


def _sharded_table_sql(base_sql: str, table_base_name: str, order_by: str) -> str:
    return (base_sql + _SHARDED_TABLE_SUFFIX_SQL.format(order_by=order_by)).format(
        table_name=f"sharded_{table_base_name}",
        engine=ReplacingMergeTree(table_base_name, ver="computed_at"),
    )


def _distributed_table_sql(base_sql: str, table_base_name: str) -> str:
    return base_sql.format(
        table_name=table_base_name,
        engine=Distributed(
            data_table=f"sharded_{table_base_name}",
            sharding_key=SHARDING_KEY,
            cluster=settings.CLICKHOUSE_AUX_CLUSTER,
        ),
    )


def SHARDED_ENGINEERING_ANALYTICS_CI_RUNS_TABLE_SQL() -> str:
    return _sharded_table_sql(
        CI_RUNS_TABLE_BASE_SQL, CI_RUNS_TABLE_BASE_NAME, "team_id, job_id, source_id, ci_engine, id"
    )


def DISTRIBUTED_ENGINEERING_ANALYTICS_CI_RUNS_TABLE_SQL() -> str:
    return _distributed_table_sql(CI_RUNS_TABLE_BASE_SQL, CI_RUNS_TABLE_BASE_NAME)


def SHARDED_ENGINEERING_ANALYTICS_CI_JOBS_TABLE_SQL() -> str:
    return _sharded_table_sql(
        CI_JOBS_TABLE_BASE_SQL, CI_JOBS_TABLE_BASE_NAME, "team_id, job_id, source_id, ci_engine, id, run_attempt"
    )


def DISTRIBUTED_ENGINEERING_ANALYTICS_CI_JOBS_TABLE_SQL() -> str:
    return _distributed_table_sql(CI_JOBS_TABLE_BASE_SQL, CI_JOBS_TABLE_BASE_NAME)
