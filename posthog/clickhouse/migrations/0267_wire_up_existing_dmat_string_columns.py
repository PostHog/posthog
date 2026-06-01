from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.dmat_slot_assignments.sql import (
    DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL,
    DMAT_SLOT_ASSIGNMENTS_TABLE_SQL,
)
from posthog.models.event.sql import (
    ALTER_TABLE_ADD_DMAT_STRING_COLUMNS,
    DROP_EVENTS_JSON_MV_SQL,
    DROP_EVENTS_JSON_WS_MV_SQL,
    DROP_KAFKA_EVENTS_JSON_TABLE_SQL,
    DROP_KAFKA_EVENTS_JSON_WS_TABLE_SQL,
    EVENTS_DATA_TABLE,
    EVENTS_TABLE_JSON_MV_SQL,
    EVENTS_TABLE_JSON_WS_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
    KAFKA_EVENTS_TABLE_JSON_WS_SQL,
)

# Wire up the existing `dmat_string_0..9` columns (added to sharded_events + events by
# migration 0179) through the rest of the events pipeline so the weekly batched dynamic
# property materialization workflow can actually use them.
#
# 0179 added 40 columns (10 each of string/numeric/bool/datetime) to sharded_events and
# events but never updated `writable_events`, `kafka_events_json[_ws]`, or
# `events_json[_ws]_mv` to project them — so plugin-server writes to dmat columns would
# be silently dropped at the Distributed boundary. This migration finishes the wiring:
#
# 1) ADD `dmat_string_0..9` to `writable_events` on every node role that hosts it
#    (DATA always, INGESTION_EVENTS on cloud — sharded_events and events already have
#    them from 0179).
# 2) DROP the legacy typed columns (`dmat_numeric_*`, `dmat_bool_*`, `dmat_datetime_*`)
#    from `sharded_events` / `events`. They were never wired into the kafka pipeline so
#    they have never received data; ALTER DROP is metadata-only on empty columns. Per
#    the dynamic property materialization design the dmat pool is string-only — HogQL
#    casts to the logical type at read time.
# 3) Recreate the kafka table and MV that feed `writable_events` so their schemas
#    project the new `dmat_string_0..9` columns. Cloud touches the WarpStream pair on
#    INGESTION_EVENTS (the only active events pipeline post-0248); non-cloud touches
#    the MSK pair on DATA. The kafka table schema is fixed at CREATE time and ignores
#    JSON keys for unknown columns, so it MUST be recreated for the MV to receive dmat
#    columns from plugin-server.
# 4) Create the `dmat_slot_assignments` table + dictionary on every host. The weekly
#    workflow writes `(team_id, slot_index) → property_name` into this table and reloads
#    the dictionary on every host before submitting the backfill mutation. The mutation
#    reads the mapping via `dictGet` / `dictHas`, which keeps the SQL constant-size
#    regardless of how many teams have adopted dmat.
#
# Layout follows the same drop-MV → drop-kafka → ALTER → recreate pattern as
# 0030_created_at_persons_and_groups_on_events, with the cloud/non-cloud split
# borrowed from migration 0238.

# Range of dmat_string columns the events pipeline now references. Stays paired with
# `DMAT_STRING_COLUMN_COUNT` in posthog/models/event/sql.py.
_STRING_RANGE_START = 0
_STRING_RANGE_END = 10  # exclusive — covers dmat_string_0..9

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


# Step 1: drop the MV and kafka table that feed into the data tables. Doing this first
# prevents a brief double-write window during the schema transition. The kafka table and
# MV are not replicated — they live independently on each host — so we run the DROP
# per-host (no ON CLUSTER, per migration conventions).
#
# Only one ingestion pipeline is live per environment: cloud uses WarpStream on
# INGESTION_EVENTS (the MSK MV on cloud DATA was left in place by migration 0248 but is
# no longer fed by plugin-server, so touching it here would be wasted work), and
# non-cloud uses MSK on DATA. Matches migration 0238's split.
if _is_cloud:
    operations = [
        run_sql_with_exceptions(
            DROP_EVENTS_JSON_WS_MV_SQL,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            DROP_KAFKA_EVENTS_JSON_WS_TABLE_SQL,
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
else:
    operations = [
        run_sql_with_exceptions(DROP_EVENTS_JSON_MV_SQL, node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DROP_KAFKA_EVENTS_JSON_TABLE_SQL, node_roles=[NodeRole.DATA]),
    ]

# Step 2a: ADD dmat_string_0..9 to writable_events. sharded_events and events already
# have these columns from migration 0179; writable_events does not. Without adding them
# here, the MV recreate below would fail to project dmat columns into writable_events.
#
# writable_events lives on DATA in every install and additionally on INGESTION_EVENTS on
# cloud (added by migration 0232); the cloud-only role is appended via the conditional.
# It is a Distributed engine table (not sharded, not replicated), so neither flag
# applies — explicit False is required to satisfy the migration convention check.
operations += [
    run_sql_with_exceptions(
        ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
            table="writable_events",
            start=_STRING_RANGE_START,
            end_exclusive=_STRING_RANGE_END,
        ),
        node_roles=([NodeRole.INGESTION_EVENTS] if _is_cloud else [NodeRole.DATA]),
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]

# Step 2b: DROP the legacy typed columns from sharded_events and events. ALTER DROP is
# metadata-only when the column has no data parts (the case here on master — the columns
# existed in the schema but nothing ever wrote to them since the kafka MV never SELECTed
# them). The IF EXISTS guards make it a no-op in environments where the columns have
# already been dropped (e.g. fresh dev installs that never ran 0179).
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

# Step 3: recreate the kafka table and MV so their schemas include dmat_string_0..9.
# `KAFKA_EVENTS_TABLE_JSON_*` and friends call EVENTS_TABLE_BASE_SQL which embeds
# `EVENTS_TABLE_DYNAMICALLY_MATERIALIZED_COLUMNS()` — now string-only — so the recreated
# tables include the 10-column dmat_string range and nothing else.
#
# Mirrors Step 1's split: WarpStream on INGESTION_EVENTS for cloud, MSK on DATA
# elsewhere. on_cluster=False because the migration framework fans the query out via
# map_hosts_by_roles, per the no-ON-CLUSTER convention.
if _is_cloud:
    operations += [
        run_sql_with_exceptions(
            KAFKA_EVENTS_TABLE_JSON_WS_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
        run_sql_with_exceptions(
            EVENTS_TABLE_JSON_WS_MV_SQL(),
            node_roles=[NodeRole.INGESTION_EVENTS],
        ),
    ]
else:
    operations += [
        run_sql_with_exceptions(
            KAFKA_EVENTS_TABLE_JSON_SQL(on_cluster=False),
            node_roles=[NodeRole.DATA],
        ),
        run_sql_with_exceptions(
            EVENTS_TABLE_JSON_MV_SQL(on_cluster=False),
            node_roles=[NodeRole.DATA],
        ),
    ]

# Step 4: create the dmat slot-assignments backing table and dictionary on the data nodes.
# The weekly batched workflow writes the current `(team_id, slot_index) → property_name`
# mapping into this table and reloads the dictionary before submitting the backfill
# mutation. The mutation reads the mapping via `dictGet` / `dictHas`, which keeps the SQL
# constant-size regardless of how many teams have adopted dmat. Until the first workflow
# run populates the table, the dict is empty and `dictHas` returns 0 for every
# (team_id, slot_index) pair, so the SET expression in the mutation falls through to keep
# the existing column value — i.e. a no-op.
# node_roles is DATA, not ALL: the table and dictionary only need to exist where
# `sharded_events` lives, because the backfill mutation runs on the data nodes and reads
# the mapping there. NodeRole.ALL additionally fans the CREATE out to the satellite
# clusters (ops/aux/sessions) via the migrations cluster, which is unnecessary here and
# was the trigger for the previous failure when a satellite was unreachable.
# Order matters: the dictionary's SOURCE references the table, so the table must be
# created first.
operations += [
    run_sql_with_exceptions(DMAT_SLOT_ASSIGNMENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
    run_sql_with_exceptions(DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
]
