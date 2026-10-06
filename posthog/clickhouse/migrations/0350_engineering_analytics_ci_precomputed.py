from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.preaggregation.engineering_analytics_ci_sql import (
    DISTRIBUTED_ENGINEERING_ANALYTICS_CI_JOBS_TABLE_SQL,
    DISTRIBUTED_ENGINEERING_ANALYTICS_CI_RUNS_TABLE_SQL,
    SHARDED_ENGINEERING_ANALYTICS_CI_JOBS_TABLE_SQL,
    SHARDED_ENGINEERING_ANALYTICS_CI_RUNS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_ENGINEERING_ANALYTICS_CI_RUNS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        SHARDED_ENGINEERING_ANALYTICS_CI_JOBS_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_ENGINEERING_ANALYTICS_CI_RUNS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_ENGINEERING_ANALYTICS_CI_JOBS_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
