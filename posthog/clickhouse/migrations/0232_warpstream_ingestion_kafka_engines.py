from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.heatmaps.sql import HEATMAPS_WS_TABLE_MV_SQL, KAFKA_HEATMAPS_WS_TABLE_SQL
from posthog.models.ai_events.sql import (
    AI_EVENTS_DATA_TABLE_SQL,
    AI_EVENTS_WS_MV_SQL,
    DISTRIBUTED_AI_EVENTS_TABLE_SQL,
    KAFKA_AI_EVENTS_WS_TABLE_SQL,
)
from posthog.models.event.sql import (
    ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS,
    EVENTS_TABLE_JSON_WS_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_WS_SQL,
)
from posthog.models.group.sql import GROUPS_WS_TABLE_MV_SQL, KAFKA_GROUPS_WS_TABLE_SQL
from posthog.models.person.sql import (
    KAFKA_PERSON_DISTINCT_ID2_WS_TABLE_SQL,
    KAFKA_PERSONS_WS_TABLE_SQL,
    PERSON_DISTINCT_ID2_WS_MV_SQL,
    PERSONS_WS_TABLE_MV_SQL,
)

# Migration to create WarpStream Kafka engine tables for core ingestion topics.
#
# These tables coexist alongside the existing MSK Kafka engine tables, reading from
# the same topics but via the warpstream_ingestion named collection. Each has its own
# consumer group to avoid conflicts with the MSK tables.
#
# CLOUD-ONLY: In non-cloud environments (CI, dev, hobby) there is only one ClickHouse
# node, so both the MSK and WS materialized views would consume the same Kafka topic
# and write to the same target table, causing every event to be counted twice.
#
# New tables:
# - kafka_events_json_ws + events_json_ws_mv (INGESTION_EVENTS)
# - kafka_groups_ws + groups_ws_mv (INGESTION_SMALL)
# - kafka_person_ws + person_ws_mv (INGESTION_SMALL)
# - kafka_person_distinct_id2_ws + person_distinct_id2_ws_mv (INGESTION_SMALL)
# - kafka_ai_events_json_ws + ai_events_json_ws_mv (AI_EVENTS)
# - kafka_heatmaps_ws + heatmaps_ws_mv (INGESTION_MEDIUM)

# The writable_events table on INGESTION_EVENTS nodes was created out-of-band and
# is missing columns that later migrations only applied to DATA nodes:
#
# - historical_migration Bool       (migration 0186 — only altered sharded_events/events on DATA)
# - consumer_breadcrumbs Array(String) (migration 0113 — only altered writable_events on DATA)
# - 40 dmat_* columns               (migration 0179 — only altered sharded_events/events on DATA)
#
# The WS MV (EVENTS_TABLE_JSON_WS_MV_SQL) SELECTs all of these, so they must exist
# on the target writable_events before the MV can be created.
ADD_MISSING_WRITABLE_EVENTS_COLUMNS = """
ALTER TABLE writable_events
    ADD COLUMN IF NOT EXISTS historical_migration Bool,
    ADD COLUMN IF NOT EXISTS consumer_breadcrumbs Array(String)
"""

operations = (
    []
    if settings.CLOUD_DEPLOYMENT not in ("US", "EU", "DEV")
    else [
        # events_json (INGESTION_EVENTS — WS tables go to events ingestion nodes)
        #
        # Backfill missing columns on writable_events for INGESTION_EVENTS nodes.
        run_sql_with_exceptions(
            ADD_MISSING_WRITABLE_EVENTS_COLUMNS,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        # dmat_* slots (40 columns) — migration 0179 only added these to DATA nodes.
        run_sql_with_exceptions(
            ALTER_TABLE_ADD_DYNAMICALLY_MATERIALIZED_COLUMNS(table="writable_events"),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            KAFKA_EVENTS_TABLE_JSON_WS_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            EVENTS_TABLE_JSON_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        # groups (INGESTION_SMALL, matching existing MSK table)
        run_sql_with_exceptions(
            KAFKA_GROUPS_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            GROUPS_WS_TABLE_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # person (INGESTION_SMALL, matching existing MSK table)
        run_sql_with_exceptions(
            KAFKA_PERSONS_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            PERSONS_WS_TABLE_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # person_distinct_id2 (INGESTION_SMALL, matching existing MSK table)
        run_sql_with_exceptions(
            KAFKA_PERSON_DISTINCT_ID2_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        run_sql_with_exceptions(
            PERSON_DISTINCT_ID2_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_SMALL],
        ),
        # ai_events (AI_EVENTS satellite cluster, matching existing MSK table)
        # Ensure sharded + distributed ai_events tables exist — they were originally
        # created only in schema.py (not a numbered migration), so the MV target
        # may be missing when migrate_clickhouse runs before test conftest setup.
        run_sql_with_exceptions(
            AI_EVENTS_DATA_TABLE_SQL(),
            node_roles=[NodeRole.AI_EVENTS],
        ),
        run_sql_with_exceptions(
            DISTRIBUTED_AI_EVENTS_TABLE_SQL(),
            node_roles=[NodeRole.AI_EVENTS],
        ),
        run_sql_with_exceptions(
            KAFKA_AI_EVENTS_WS_TABLE_SQL(),
            node_roles=[NodeRole.AI_EVENTS],
        ),
        run_sql_with_exceptions(
            AI_EVENTS_WS_MV_SQL(),
            node_roles=[NodeRole.AI_EVENTS],
        ),
        # heatmaps (INGESTION_MEDIUM, matching existing MSK table)
        run_sql_with_exceptions(
            KAFKA_HEATMAPS_WS_TABLE_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
        run_sql_with_exceptions(
            HEATMAPS_WS_TABLE_MV_SQL(),
            node_roles=[NodeRole.INGESTION_MEDIUM],
        ),
    ]
)
