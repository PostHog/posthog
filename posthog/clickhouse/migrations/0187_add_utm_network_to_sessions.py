from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.raw_sessions.sessions_v2 import (
    RAW_SESSION_TABLE_UPDATE_SQL,
    SHARDED_RAW_SESSIONS_DATA_TABLE,
    TABLE_BASE_NAME,
    WRITABLE_RAW_SESSIONS_DATA_TABLE,
)

ADD_UTM_NETWORK_COLUMN = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS initial_utm_network AggregateFunction(argMin, String, DateTime64(6, 'UTC')) AFTER initial_utm_content
"""

operations = [
    # Add initial_utm_network column to sharded table
    run_sql_with_exceptions(
        ADD_UTM_NETWORK_COLUMN.format(table_name=SHARDED_RAW_SESSIONS_DATA_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    # Add initial_utm_network column to writable table
    run_sql_with_exceptions(
        ADD_UTM_NETWORK_COLUMN.format(table_name=WRITABLE_RAW_SESSIONS_DATA_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Add initial_utm_network column to distributed table
    run_sql_with_exceptions(
        ADD_UTM_NETWORK_COLUMN.format(table_name=TABLE_BASE_NAME),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    # Update the materialized view to include utm_network
    run_sql_with_exceptions(
        RAW_SESSION_TABLE_UPDATE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
