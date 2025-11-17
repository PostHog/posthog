from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.duplicate_events.sql import (
    DUPLICATE_EVENTS_MV_SQL,
    DUPLICATE_EVENTS_TABLE_SQL,
    DUPLICATE_EVENTS_WRITABLE_TABLE_SQL,
    KAFKA_DUPLICATE_EVENTS_TABLE_SQL,
)

operations = [
    run_sql_with_exceptions(DUPLICATE_EVENTS_TABLE_SQL(), node_roles=[NodeRole.DATA, NodeRole.COORDINATOR]),
    run_sql_with_exceptions(DUPLICATE_EVENTS_WRITABLE_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(KAFKA_DUPLICATE_EVENTS_TABLE_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
    run_sql_with_exceptions(DUPLICATE_EVENTS_MV_SQL(), node_roles=[NodeRole.INGESTION_SMALL]),
]
