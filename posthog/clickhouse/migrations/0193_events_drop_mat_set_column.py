from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DROP_MINMAX_MAT_SET_INDEX = """
ALTER TABLE sharded_events DROP INDEX IF EXISTS `minmax_mat_$set`
"""

DROP_MAT_SET_FROM_EVENTS = """
ALTER TABLE events DROP COLUMN IF EXISTS `mat_$set`
"""

DROP_MAT_SET_FROM_SHARDED_EVENTS = """
ALTER TABLE sharded_events DROP COLUMN IF EXISTS `mat_$set`
"""

operations = [
    run_sql_with_exceptions(
        DROP_MAT_SET_FROM_EVENTS,
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        DROP_MINMAX_MAT_SET_INDEX,
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        DROP_MAT_SET_FROM_SHARDED_EVENTS,
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
]
