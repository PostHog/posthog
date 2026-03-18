from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

REMOVE_MAT_SET_COLUMN_COMMENT = """
ALTER TABLE events COMMENT COLUMN IF EXISTS `mat_$set` ''
"""

operations = [
    run_sql_with_exceptions(
        REMOVE_MAT_SET_COLUMN_COMMENT,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
