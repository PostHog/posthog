from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

ADD_MINMAX_INDEX_TIMESTAMP = """
ALTER TABLE sharded_events
ADD INDEX IF NOT EXISTS minmax_sharded_events_timestamp timestamp
TYPE minmax
GRANULARITY 1
"""

operations = [
    run_sql_with_exceptions(
        ADD_MINMAX_INDEX_TIMESTAMP,
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
