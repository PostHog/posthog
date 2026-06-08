from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.session_recordings.sql.session_replay_event_sql import (
    KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL,
    SESSION_REPLAY_EVENTS_WS_MV_SQL,
)
from posthog.session_recordings.sql.session_replay_feature_sql import (
    KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL,
    SESSION_REPLAY_FEATURES_WS_MV_SQL,
)

# Migration to create WarpStream Kafka engine tables for session_replay_events and
# session_replay_features.
#
# These tables coexist alongside the existing MSK Kafka engine tables, reading from
# the same topics but via the warpstream_replay named collection. Each has its own
# consumer group to avoid conflicts with the MSK tables.
#
# CLOUD-ONLY: In non-cloud environments (CI, dev, hobby) there is only one ClickHouse
# node, so both the MSK and WS materialized views would consume the same Kafka topic
# and write to the same target table, doubling every row.
#
# New tables:
# - kafka_session_replay_events_ws + session_replay_events_ws_mv (INGESTION_SMALL)
# - kafka_session_replay_features_ws + session_replay_features_ws_mv (INGESTION_MEDIUM)

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        # session_replay_events (INGESTION_SMALL, matching existing MSK table)
        run_sql_with_exceptions(
            KAFKA_SESSION_REPLAY_EVENTS_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            SESSION_REPLAY_EVENTS_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # session_replay_features (INGESTION_MEDIUM, matching existing MSK table)
        run_sql_with_exceptions(
            KAFKA_SESSION_REPLAY_FEATURES_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            SESSION_REPLAY_FEATURES_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
    ]
)
