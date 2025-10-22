from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    DROP_EVENTS_RECENT_MV_TABLE_SQL,
    DROP_KAFKA_EVENTS_RECENT_TABLE_SQL,
    EVENTS_RECENT_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_RECENT_TABLE_JSON_SQL,
    WRITABLE_EVENTS_RECENT_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DROP_KAFKA_EVENTS_RECENT_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(DROP_EVENTS_RECENT_MV_TABLE_SQL(), node_roles=NodeRole.DATA),
    run_sql_with_exceptions(WRITABLE_EVENTS_RECENT_TABLE_SQL(on_cluster=False), node_roles=NodeRole.INGESTION_MEDIUM),
    run_sql_with_exceptions(KAFKA_EVENTS_RECENT_TABLE_JSON_SQL(on_cluster=False), node_roles=NodeRole.INGESTION_MEDIUM),
    run_sql_with_exceptions(EVENTS_RECENT_TABLE_JSON_MV_SQL(), node_roles=NodeRole.INGESTION_MEDIUM),
]
