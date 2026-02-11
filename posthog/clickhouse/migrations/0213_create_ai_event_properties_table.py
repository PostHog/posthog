from posthog.clickhouse.client.migration_tools import NodeRole, run_sql_with_exceptions
from posthog.models.event.ai_properties_sql import (
    AI_EVENT_PROPERTIES_MV_SQL,
    DISTRIBUTED_AI_EVENT_PROPERTIES_TABLE_SQL,
    KAFKA_AI_EVENT_PROPERTIES_TABLE_SQL,
    SHARDED_AI_EVENT_PROPERTIES_TABLE_SQL,
    WRITABLE_AI_EVENT_PROPERTIES_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_AI_EVENT_PROPERTIES_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_AI_EVENT_PROPERTIES_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        WRITABLE_AI_EVENT_PROPERTIES_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        KAFKA_AI_EVENT_PROPERTIES_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        AI_EVENT_PROPERTIES_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
