from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    EVENTS_SHARDED_RECENT_TABLE_JSON_MV_SQL,
    KAFKA_SHARDED_EVENTS_RECENT_TABLE_JSON_SQL,
    SHARDED_EVENTS_RECENT_TABLE_SQL,
    SHARDED_WRITABLE_EVENTS_RECENT_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(
        SHARDED_EVENTS_RECENT_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        SHARDED_WRITABLE_EVENTS_RECENT_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        KAFKA_SHARDED_EVENTS_RECENT_TABLE_JSON_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
    run_sql_with_exceptions(
        EVENTS_SHARDED_RECENT_TABLE_JSON_MV_SQL(),
        node_roles=[NodeRole.INGESTION_SMALL],
    ),
]
