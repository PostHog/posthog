from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.clickhouse.distributed_system_processes import DISTRIBUTED_SYSTEM_PROCESSES_TABLE_SQL

operations = [
    run_sql_with_exceptions(
        DISTRIBUTED_SYSTEM_PROCESSES_TABLE_SQL(on_cluster=False),
        node_role=NodeRole.ALL,
    ),
]
