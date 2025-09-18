from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.log_entries import LOG_ENTRIES_DISTRIBUTED_TABLE, LOG_ENTRIES_TABLE

DROP_LOG_ENTRIES_SQL = f"""
DROP TABLE IF EXISTS {LOG_ENTRIES_DISTRIBUTED_TABLE}
"""  # We drop the one with "distributed" in its name because after the exchange in migration 0143_log_entries_exchange.py it's the old table

DROP_KAFKA_LOG_ENTRIES_SQL = f"""
DROP TABLE IF EXISTS kafka_{LOG_ENTRIES_TABLE}
"""

operations = [
    run_sql_with_exceptions(DROP_KAFKA_LOG_ENTRIES_SQL, node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DROP_LOG_ENTRIES_SQL, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
]
