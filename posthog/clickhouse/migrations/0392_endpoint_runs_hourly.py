from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.clickhouse.endpoint_runs import (
    DISTRIBUTED_ENDPOINT_RUNS_HOURLY_TABLE_SQL,
    SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE_SQL,
    SHARDED_ENDPOINT_RUNS_HOURLY_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(SHARDED_ENDPOINT_RUNS_HOURLY_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(SHARDED_ENDPOINT_RUNS_HOURLY_STAGING_TABLE_SQL(), node_roles=[NodeRole.AUX]),
    run_sql_with_exceptions(DISTRIBUTED_ENDPOINT_RUNS_HOURLY_TABLE_SQL(), node_roles=[NodeRole.AUX, NodeRole.DATA]),
]
