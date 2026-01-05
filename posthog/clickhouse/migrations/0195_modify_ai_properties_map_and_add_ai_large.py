from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_groups import property_groups

operations = [
    # Modify the existing "ai" property group to exclude large properties
    *[
        run_sql_with_exceptions(statement, node_roles=[NodeRole.DATA], sharded=True)
        for statement in [*property_groups.get_alter_modify_statements("sharded_events", "properties", "ai")]
    ],
    *[
        run_sql_with_exceptions(statement, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR])
        for statement in [*property_groups.get_alter_modify_statements("events", "properties", "ai")]
    ],
    # Create the new "ai_large" property group for large properties
    *[
        run_sql_with_exceptions(statement, node_roles=[NodeRole.DATA], sharded=True)
        for statement in [*property_groups.get_alter_create_statements("sharded_events", "properties", "ai_large")]
    ],
    *[
        run_sql_with_exceptions(statement, node_roles=[NodeRole.DATA, NodeRole.COORDINATOR])
        for statement in [*property_groups.get_alter_create_statements("events", "properties", "ai_large")]
    ],
]
