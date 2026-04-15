from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import (
    DISTRIBUTED_PROPERTY_VALUES_TABLE_SQL,
    PROPERTY_VALUES_MV_SQL,
    PROPERTY_VALUES_TABLE_SQL,
    WRITABLE_PROPERTY_VALUES_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        PROPERTY_VALUES_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    run_sql_with_exceptions(
        WRITABLE_PROPERTY_VALUES_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        PROPERTY_VALUES_MV_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_PROPERTY_VALUES_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
