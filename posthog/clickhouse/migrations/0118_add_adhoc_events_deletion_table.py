from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions, NodeRole
from posthog.clickhouse.adhoc_events_deletion import ADHOC_EVENTS_DELETION_TABLE_SQL

operations = [
    run_sql_with_exceptions(
        ADHOC_EVENTS_DELETION_TABLE_SQL(on_cluster=False),
        node_role=NodeRole.ALL,
    ),
]
