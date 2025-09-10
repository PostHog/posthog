from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import LOG_ENTRIES_DISTRIBUTED_TABLE, LOG_ENTRIES_TABLE

EXCHANGE_LOG_ENTRIES_SQL = f"""
EXCHANGE TABLES {LOG_ENTRIES_TABLE} AND {LOG_ENTRIES_DISTRIBUTED_TABLE}
"""

operations = [
    run_sql_with_exceptions(EXCHANGE_LOG_ENTRIES_SQL, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
]
