from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    # Drop MV first (stops writes)
    run_sql_with_exceptions(
        "DROP VIEW IF EXISTS property_values_mv SYNC",
        node_roles=[NodeRole.DATA],
    ),
    # Drop writable distributed table
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS writable_property_values SYNC",
        node_roles=[NodeRole.DATA],
    ),
    # Drop read distributed table
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS property_values_distributed SYNC",
        node_roles=[NodeRole.DATA],
    ),
    # Drop raw table
    run_sql_with_exceptions(
        "DROP TABLE IF EXISTS property_values SYNC",
        node_roles=[NodeRole.AUX],
    ),
]
