from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.query_log_archive import ADD_TEAM_ID_ALIAS_COLUMN

operations = [
    run_sql_with_exceptions(
        ADD_TEAM_ID_ALIAS_COLUMN,
        node_role=NodeRole.ALL,
        is_alter_on_replicated_table=True,
    ),
]
