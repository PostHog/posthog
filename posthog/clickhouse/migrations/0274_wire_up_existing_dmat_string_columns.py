from posthog import settings
from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.models.dmat_slot_assignments.sql import (
    DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL,
    DMAT_SLOT_ASSIGNMENTS_TABLE_SQL,
)
from posthog.models.event.sql import (
    ALTER_TABLE_ADD_DMAT_STRING_COLUMNS,
    DMAT_STRING_COLUMN_COUNT,
    DROP_EVENTS_JSON_MV_SQL,
    DROP_KAFKA_EVENTS_JSON_TABLE_SQL,
    EVENTS_TABLE_JSON_MV_SQL,
    KAFKA_EVENTS_TABLE_JSON_SQL,
)

# Wire up the existing `dmat_string_0..9` columns (added to sharded_events + events by
# migration 0179) through the rest of the events pipeline so the weekly batched dynamic
# property materialization workflow can use them. Third attempt — 0256 was reverted in
# #59350 and 0267 in #61041; the 0267 run caused the 2026-06-01 ingestion incident.
#
# This migration is a deliberate NO-OP on cloud (US/EU/DEV). Per the post-incident
# guidance from the ClickHouse team, schema changes to the events table and the
# ingestion pipeline on cloud are applied manually by the ClickHouse team and recorded
# in the repo afterwards. The two reasons this cannot run unattended on cloud:
#
# 1. The live cloud ingestion schemas have drifted from the repo SQL. The kafka table /
#    MV pair on cloud is the WarpStream pair (`kafka_events_json_ws` /
#    `events_json_ws_mv`), whose definitions carry dozens of environment-specific
#    `mat_*` columns that are not reflected in the repo — recreating them from repo SQL
#    destroys the live schema and breaks ingestion (this is exactly what 0267 did).
#    They are a no-go zone; see posthog/clickhouse/migrations/AGENTS.md.
# 2. The cloud topologies differ from each other and from the repo's role assumptions
#    (e.g. `writable_events` does not exist on DATA nodes in US prod — it lives on the
#    ingestion layer, which is itself mid-migration from EKS to EC2).
#
# The manual steps for cloud are in 0274_wire_up_existing_dmat_string_columns.runbook.md
# next to this file. Local/hobby installs match the repo SQL exactly (they only ever ran
# our migrations), so the wiring below is safe there.
#
# Differences from the reverted 0267, beyond the cloud gate:
#
# - No DROP COLUMN. 0267 dropped the never-wired typed dmat columns
#   (`dmat_numeric_*`/`dmat_bool_*`/`dmat_datetime_*`, also from 0179) from
#   sharded_events/events; in EU those mutations stuck on pre-`inserted_at` parts with
#   NOT_FOUND_COLUMN_IN_BLOCK and had to be killed by hand. Column removal now follows
#   the two-step process (ClickHouse team drops manually first, repo records it after);
#   the typed columns are empty and harmless in the meantime, so they stay.
# - The additive `writable_events` ALTER runs before the kafka/MV drop. 0267 dropped
#   the MV first, then failed on the ALTER, leaving ingestion down with nothing to
#   recreate. Ordering the fallible-but-safe ALTER first means a failure aborts the
#   migration with the pipeline untouched.
#
# Fresh installs get all of this from posthog/clickhouse/schema.py (the dmat columns and
# the slot-assignments table/dictionary are already in the canonical CREATEs); this
# migration only retrofits existing non-cloud installs. Every statement is idempotent
# (IF NOT EXISTS / IF EXISTS), so installs that briefly applied 0267 converge too.

if settings.CLOUD_DEPLOYMENT in ("US", "EU", "DEV"):
    operations = []
else:
    operations = [
        # Step 1: additive schema changes, safe to fail without touching ingestion.
        # sharded_events and events already have dmat_string_0..9 from 0179;
        # writable_events is the missing hop. It is a Distributed table (not sharded,
        # not replicated), so the ALTER is metadata-only and both flags are False.
        run_sql_with_exceptions(
            ALTER_TABLE_ADD_DMAT_STRING_COLUMNS(
                table="writable_events",
                start=0,
                end_exclusive=DMAT_STRING_COLUMN_COUNT,
            ),
            node_roles=[NodeRole.DATA],
            sharded=False,
            is_alter_on_replicated_table=False,
        ),
        # Step 2: the dmat slot-assignments backing table and dictionary, on the data
        # nodes where the backfill mutation reads them via dictGet/dictHas. New objects
        # with no interaction with existing schema. The dictionary's SOURCE references
        # the table, so the table must be created first.
        run_sql_with_exceptions(DMAT_SLOT_ASSIGNMENTS_TABLE_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DMAT_SLOT_ASSIGNMENTS_DICTIONARY_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
        # Step 3: recreate the MSK kafka table and MV so their schemas include
        # dmat_string_0..9. The kafka table schema is fixed at CREATE time and ignores
        # JSON keys for unknown columns, so it must be recreated for the MV to project
        # dmat values from plugin-server into writable_events. MV dropped first to
        # avoid a double-write window; neither object is replicated, so the drop and
        # recreate run per-host (no SYNC needed). Ingestion pauses for the instants
        # between the drops and the recreates and resumes from committed offsets.
        run_sql_with_exceptions(DROP_EVENTS_JSON_MV_SQL, node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(DROP_KAFKA_EVENTS_JSON_TABLE_SQL, node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(KAFKA_EVENTS_TABLE_JSON_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
        run_sql_with_exceptions(EVENTS_TABLE_JSON_MV_SQL(on_cluster=False), node_roles=[NodeRole.DATA]),
    ]
