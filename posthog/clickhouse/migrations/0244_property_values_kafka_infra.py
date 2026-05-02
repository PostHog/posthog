from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.property_values import (
    DISTRIBUTED_PROPERTY_VALUES_TABLE_SQL,
    KAFKA_PROPERTY_VALUES_TABLE_SQL_FN,
    PROPERTY_VALUES_MV_SQL,
    PROPERTY_VALUES_TABLE_SQL,
)

operations = [
    # 1. Raw table on AUX
    run_sql_with_exceptions(
        PROPERTY_VALUES_TABLE_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 2. Kafka engine table on AUX (consumes from clickhouse_property_values topic)
    run_sql_with_exceptions(
        KAFKA_PROPERTY_VALUES_TABLE_SQL_FN(),
        node_roles=[NodeRole.AUX],
    ),
    # 3. MV on AUX (Kafka -> raw table)
    run_sql_with_exceptions(
        PROPERTY_VALUES_MV_SQL(),
        node_roles=[NodeRole.AUX],
    ),
    # 4. Distributed read table on AUX and DATA
    run_sql_with_exceptions(
        DISTRIBUTED_PROPERTY_VALUES_TABLE_SQL(),
        node_roles=[NodeRole.AUX, NodeRole.DATA],
    ),
]
