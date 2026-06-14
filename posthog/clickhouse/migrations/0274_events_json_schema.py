from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    DISTRIBUTED_EVENTS_JSON_TABLE_SQL,
    EVENTS_JSON_TABLE_MV_SQL,
    EVENTS_JSON_TABLE_SQL,
    WRITABLE_EVENTS_JSON_TABLE_SQL,
)
from posthog.models.raw_sessions.sessions_v2 import RAW_SESSION_TABLE_UPDATE_SQL
from posthog.models.raw_sessions.sessions_v3 import RAW_SESSION_TABLE_MV_UPDATE_SQL_V3, RAW_SESSIONS_TABLE_MV_SQL_V3
from posthog.models.sessions.sql import SESSION_TABLE_UPDATE_SQL

operations = [
    run_sql_with_exceptions(
        EVENTS_JSON_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        WRITABLE_EVENTS_JSON_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_EVENTS_JSON_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    # Dual-write MV: populates the native-JSON events table from the existing events_json Kafka
    # stream alongside the legacy events_json_mv, so the JSON table stays in lockstep regardless of
    # CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA.
    run_sql_with_exceptions(
        EVENTS_JSON_TABLE_MV_SQL(on_cluster=False),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        SESSION_TABLE_UPDATE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        RAW_SESSION_TABLE_UPDATE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        RAW_SESSIONS_TABLE_MV_SQL_V3(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        RAW_SESSION_TABLE_MV_UPDATE_SQL_V3(),
        node_roles=[NodeRole.DATA],
    ),
]
