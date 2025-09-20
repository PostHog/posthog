from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_groups import property_groups

operations = [
    *[
        run_sql_with_exceptions(statement, node_roles=[NodeRole.DATA], sharded=True)
        for statement in [*property_groups.get_alter_create_statements("sharded_events", "properties", "ai")]
    ],
    *[
        run_sql_with_exceptions(statement, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR])
        for statement in [*property_groups.get_alter_create_statements("events", "properties", "ai")]
    ],
]
