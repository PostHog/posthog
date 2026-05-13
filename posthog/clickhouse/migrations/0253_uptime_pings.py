from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

from products.uptime.backend.sql import DISTRIBUTED_UPTIME_PINGS_TABLE_SQL, SHARDED_UPTIME_PINGS_TABLE_SQL

operations = [
    run_sql_with_exceptions(
        SHARDED_UPTIME_PINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_UPTIME_PINGS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
