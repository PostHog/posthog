from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.ai_events.sql import (
    AI_EVENTS_DATA_TABLE_SQL,
    AI_EVENTS_MV_SQL,
    DISTRIBUTED_AI_EVENTS_TABLE_SQL,
    KAFKA_AI_EVENTS_TABLE_SQL,
    WRITABLE_AI_EVENTS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        AI_EVENTS_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_AI_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        WRITABLE_AI_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        KAFKA_AI_EVENTS_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        AI_EVENTS_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]
