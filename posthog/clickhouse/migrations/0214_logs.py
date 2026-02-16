from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.logs import LOGS_DISTRIBUTED_TABLE_SQL

operations = [
    run_sql_with_exceptions(
        LOGS_DISTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.LOGS],
    ),
]
