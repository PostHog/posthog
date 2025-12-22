from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

REMOVE_MAT_SET_DEFAULT = """
ALTER TABLE sharded_events MODIFY COLUMN IF EXISTS `mat_$set` REMOVE DEFAULT
"""

operations = [
    run_sql_with_exceptions(
        REMOVE_MAT_SET_DEFAULT,
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
