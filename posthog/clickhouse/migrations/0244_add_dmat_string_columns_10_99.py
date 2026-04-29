from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.dmat_slot_assignments.sql import (
    DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL,
    DMAT_SLOT_ASSIGNMENTS_TABLE_SQL,
)
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

# Two interlocking schema changes:
#
# 1) Expand the dmat_string column pool from 10 to 100 columns to support the weekly
#    batched dynamic property materialization workflow. NULL columns compress to near-zero
#    (a few bytes per granule for the null bitmap), so the unused capacity is essentially
#    free and gives ~19 weeks of runway at 5 columns/week before compaction is needed.
#
# 2) Drop the legacy typed dmat columns (`dmat_numeric_*`, `dmat_bool_*`, `dmat_datetime_*`)
#    that were added in migration 0179 to `sharded_events` / `events` only — they were never
#    wired into the kafka tables / MV / writable_events on master, so they have never received
#    any data. Per the dynamic property materialization RFC the dmat pool is string-only;
#    HogQL casts to the property's logical type at query time using the same wrapper it
#    applies to normal `mat_*` columns.
#
# Layout follows the same drop-MV → drop-kafka → ALTER data tables → recreate pattern as
# 0030_created_at_persons_and_groups_on_events for the MSK path, and the pattern from 0232
# for the cloud-only WarpStream path. The kafka tables and MVs MUST be recreated because:
#   - the MV's SELECT lists every dmat_string column from MV_DYNAMICALLY_MATERIALIZED_COLUMNS()
#   - the kafka table schema is fixed at CREATE time and ignores JSON keys for unknown columns
# Without recreating both, plugin-server writes to dmat_string_10..99 would be silently
# dropped before reaching writable_events.

_NEW_STRING_RANGE_START = 10
_NEW_STRING_RANGE_END = 100  # exclusive

# The typed columns added by 0179. Hard-coded here so this migration is self-contained
# even if the surrounding code drops every reference to typed dmat columns.
_LEGACY_TYPED_COLUMN_COUNT = 10

_is_cloud = settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV")


def _drop_typed_columns_clauses() -> str:
    pieces: list[str] = []
    for prefix in ("dmat_numeric_", "dmat_bool_", "dmat_datetime_"):
        for i in range(_LEGACY_TYPED_COLUMN_COUNT):
            pieces.append(f"DROP COLUMN IF EXISTS `{prefix}{i}`")
    return ",\n  ".join(pieces)


def _alter_drop_typed(table: str) -> str:
    return f"ALTER TABLE {table} \n  {_drop_typed_columns_clauses()}"


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

# Step 2a: ADD the new dmat_string columns to every table the events_json_mv SELECT touches
# AND every table writable_events fans out from. Skipping any of these would either fail the
# MV recreate (if the target lacks a column the SELECT projects) or silently drop columns at
# the Distributed boundary on the path that's still missing the schema.
#
# Tables and where they live:
# - sharded_events: data nodes only (sharded)
# - events: DATA nodes (distributed read table)
# - writable_events: DATA nodes always (legacy MSK path), AND INGESTION_EVENTS nodes on cloud
#   (WarpStream path added in 0232 — see that migration for why this is cloud-only)
operations += [
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
    # writable_events on DATA nodes — required on every install so the MSK MV recreate below
    # can project dmat_string_10..99 into it. Without this, self-hosted installs (which have
    # no INGESTION_EVENTS path at all) would fail at the MV recreate step.
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
            table="writable_events",
            start=_NEW_STRING_RANGE_START,
            end_exclusive=_NEW_STRING_RANGE_END,
        ),
        node_roles=[NodeRole.DATA],
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

# Step 2b: DROP the legacy typed columns. ALTER DROP is metadata-only when the column has no
# data parts (the case here on master — the columns existed in the schema but nothing ever
# wrote to them since the kafka MV never SELECTed them). The IF EXISTS guards make it a no-op
# in environments where the columns have already been dropped (e.g. fresh dev installs that
# never ran 0179).
operations += [
    run_sql_with_exceptions(
        _alter_drop_typed(EVENTS_DATA_TABLE()),
        node_roles=[NodeRole.DATA],
        sharded=True,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        _alter_drop_typed("events"),
        node_roles=[NodeRole.DATA],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]

if _is_cloud:
    operations += [
        run_sql_with_exceptions(
            _alter_drop_typed("writable_events"),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]

# Step 3: recreate the kafka tables and MVs with the new full schema.
# `KAFKA_EVENTS_TABLE_JSON_SQL()` and friends call EVENTS_TABLE_BASE_SQL which embeds
# `EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS()` — now string-only — so the recreated
# tables include the expanded 100-column dmat_string range and nothing else.
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

# Step 4: create the dmat slot-assignments backing table and dictionary on
# every host. The weekly batched workflow writes the current
# `(team_id, column_index) → property_name` mapping into this table and reloads
# the dictionary on every host before submitting the backfill mutation. The
# mutation reads the mapping via `dictGet`/`dictHas`, which keeps the SQL a
# constant size regardless of how many teams have adopted dmat. Until the first
# workflow run populates the table the dict is empty and `dictHas` returns 0
# for every (team_id, column_index) pair, so the SET expression in the
# mutation falls through to keep the existing column value — i.e. a no-op.
# Order matters: the dictionary's SOURCE references the table, so the table
# must be created first.
operations += [
    run_sql_with_exceptions(DMAT_SLOT_ASSIGNMENTS_TABLE_SQL(on_cluster=True)),
    run_sql_with_exceptions(DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL(on_cluster=True)),
]
