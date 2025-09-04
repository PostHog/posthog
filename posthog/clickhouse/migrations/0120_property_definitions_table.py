from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.property_definition import PROPERTY_DEFINITIONS_TABLE_SQL

operations = [
    run_sql_with_exceptions(PROPERTY_DEFINITIONS_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
]
