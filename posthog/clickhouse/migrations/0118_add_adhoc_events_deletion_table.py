from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE_SQL
from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        ADHOC_EVENTS_DELETION_TABLE_SQL(on_cluster=False),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
]
