from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event_properties.sql import (
    EVENT_PROPERTIES_DISTRIBUTED_TABLE_SQL,
    EVENT_PROPERTIES_MV_SQL,
    EVENT_PROPERTIES_SHARDED_TABLE_SQL,
    EVENT_PROPERTIES_WRITABLE_TABLE_SQL,
    KAFKA_EVENT_PROPERTIES_TABLE_SQL,
)

operations = [
    # 1. Sharded data table (on data nodes)
    run_sql_with_exceptions(
        EVENT_PROPERTIES_SHARDED_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
        sharded=True,
    ),
    # 2. Distributed read table (on data + coordinator nodes)
    run_sql_with_exceptions(
        EVENT_PROPERTIES_DISTRIBUTED_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    # 3. Writable distributed table (on ingestion nodes)
    run_sql_with_exceptions(
        EVENT_PROPERTIES_WRITABLE_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 4. Kafka table (on ingestion nodes)
    run_sql_with_exceptions(
        KAFKA_EVENT_PROPERTIES_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    # 5. Materialized view (on ingestion nodes)
    run_sql_with_exceptions(
        EVENT_PROPERTIES_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
