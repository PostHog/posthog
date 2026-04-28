from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.event.sql import (
    ALTER_TABLE_ADD_DMAT_STRING_COLUMNS,
    DROP_EVENTS_JSON_WS_MV_SQL,
    DROP_KAFKA_EVENTS_JSON_WS_TABLE_SQL,
    EVENTS_DATA_TABLE,
    EVENTS_TABLE_JSON_MV_SQL,
    EVENTS_TABLE_JSON_WS_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
    KAFKA_EVENTS_TABLE_JSON_WS_SQL,
)
from posthog.settings import CLICKHOUSE_CLUSTER

# Expand the dmat_string column pool from 10 to 100 columns to support the weekly
# batched dynamic property materialization workflow. NULL columns compress to near-zero
# (a few bytes per granule for the null bitmap), so the unused capacity is essentially
# free and gives ~19 weeks of runway at 5 columns/week before compaction is needed.
#
# Existing dmat_numeric_*, dmat_bool_*, and dmat_datetime_* columns remain in the schema
# but are no longer assigned to new slots — the new design is string-only with HogQL
# casting at query time.
#
# This migration follows the same drop-MV → drop-kafka → ALTER data tables → recreate
# pattern as 0030_created_at_persons_and_groups_on_events for the MSK path, and the
# pattern from 0232 for the cloud-only WarpStream path. The kafka tables and MVs MUST
# be recreated because:
#   - the MV's SELECT lists every dmat_string column from MV_DYNAMICALLY_MATERIALIZED_COLUMNS()
#   - the kafka table schema is fixed at CREATE time and ignores JSON keys for unknown columns
# Without recreating both, plugin-server writes to dmat_string_10..99 would be silently
# dropped before reaching writable_events.

_NEW_STRING_RANGE_START = 10
_NEW_STRING_RANGE_END = 100  # exclusive

_is_cloud = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")

# Step 1: drop the MVs and the kafka tables that feed into the data tables.
# Doing this first prevents a brief double-write window during the schema transition.
operations = [
    # MSK path (legacy, present everywhere).
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS events_json_mv ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
    run_sql_with_exceptions(f"DROP TABLE IF EXISTS kafka_events_json ON CLUSTER '{CLICKHOUSE_CLUSTER}'"),
]

if _is_cloud:
    # WarpStream path (cloud-only — see migration 0232 for why).
    operations += [
        run_sql_with_exceptions(
            DROP_EVENTS_JSON_WS_MV_SQL,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            DROP_KAFKA_EVENTS_JSON_WS_TABLE_SQL,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]

# Step 2: ALTER the data tables (where the new columns physically live).
operations += [
    # sharded_events / events on DATA nodes (matches migration 0179's split).
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
            table=EVENTS_DATA_TABLE(),
            start=_NEW_STRING_RANGE_START,
            end_exclusive=_NEW_STRING_RANGE_END,
        ),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
            table="events",
            start=_NEW_STRING_RANGE_START,
            end_exclusive=_NEW_STRING_RANGE_END,
        ),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]

if _is_cloud:
    # writable_events on INGESTION_EVENTS nodes (matches migration 0232's split for the WS path).
    operations += [
        run_sql_with_exceptions(
            ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
                table="writable_events",
                start=_NEW_STRING_RANGE_START,
                end_exclusive=_NEW_STRING_RANGE_END,
            ),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]

# Step 3: recreate the kafka tables and MVs with the new full schema.
# `KAFKA_EVENTS_TABLE_JSON_SQL()` and friends call EVENTS_TABLE_BASE_SQL which embeds
# `EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS()`, so the recreated tables include the
# expanded 100-column dmat_string range automatically.
operations += [
    # MSK path
    run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL()),
    run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL()),
]

if _is_cloud:
    operations += [
        # WarpStream path (cloud-only)
        run_sql_with_exceptions(
            KAFKA_EVENTS_TABLE_JSON_WS_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            EVENTS_TABLE_JSON_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
