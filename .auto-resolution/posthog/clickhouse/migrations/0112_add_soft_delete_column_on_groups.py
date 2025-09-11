from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DROP_COLUMNS_INDEX_GROUPS = """
ALTER TABLE groups
DROP INDEX IF EXISTS is_deleted_idx
"""

DROP_COLUMNS_GROUPS = """
ALTER TABLE groups
DROP COLUMN IF EXISTS is_deleted
"""

ADD_COLUMNS_GROUPS = """
ALTER TABLE groups
ADD COLUMN IF NOT EXISTS is_deleted Boolean
"""

ADD_COLUMNS_INDEX_GROUPS = """
ALTER TABLE groups
ADD INDEX IF NOT EXISTS is_deleted_idx (is_deleted) TYPE minmax GRANULARITY 1
"""

operations = [
    run_sql_with_exceptions(
        DROP_COLUMNS_INDEX_GROUPS, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR], is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        DROP_COLUMNS_GROUPS, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR], is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        ADD_COLUMNS_GROUPS, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR], is_alter_on_replicated_table=True
    ),
    run_sql_with_exceptions(
        ADD_COLUMNS_INDEX_GROUPS, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR], is_alter_on_replicated_table=True
    ),
]
