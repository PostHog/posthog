from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_event_summaries_sql import (
    DISTRIBUTED_SESSION_EVENT_SUMMARIES_TABLE_SQL,
    SESSION_EVENT_SUMMARIES_DATA_TABLE_SQL,
    SESSION_EVENT_SUMMARIES_MV_SQL,
    WRITABLE_SESSION_EVENT_SUMMARIES_TABLE_SQL,
)

# Lookup table for which event types occurred per session recording.
# Populated by a materialized view on kafka_events_json (second MV on the same Kafka table).
#
# Enables:
# 1. Event-name filtering without scanning the events table
# 2. Test account filtering via pre-extracted distinct_hosts and distinct_emails
# 3. Pre-filtering for property queries by narrowing session_id candidates
#
# Architecture:
# - sharded_session_event_summaries: AggregatingMergeTree on DATA nodes
# - session_event_summaries: Distributed read table on DATA + COORDINATOR nodes
# - writable_session_event_summaries: Distributed write table on INGESTION_MEDIUM nodes
# - session_event_summaries_mv: MV on INGESTION_MEDIUM nodes (reads from existing kafka_events_json)

operations = [
    run_sql_with_exceptions(
        SESSION_EVENT_SUMMARIES_DATA_TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_SESSION_EVENT_SUMMARIES_TABLE_SQL(),
        node_roles=[NodeRole.DATA, NodeRole.COORDINATOR],
    ),
    run_sql_with_exceptions(
        WRITABLE_SESSION_EVENT_SUMMARIES_TABLE_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
    run_sql_with_exceptions(
        SESSION_EVENT_SUMMARIES_MV_SQL(),
        node_roles=[NodeRole.INGESTION_MEDIUM],
    ),
]
