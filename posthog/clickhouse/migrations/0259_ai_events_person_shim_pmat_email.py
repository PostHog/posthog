from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

# Add the `pmat_email` materialized-column shim to the Distributed `person`
# table on the ai_events satellite cluster. The column lives as a real
# materialized column on the main cluster's `person` table (created by
# `ee.clickhouse.materialized_columns.columns.materialize("person", "email")`),
# but the AI_EVENTS shim is created with `extra_fields=""` and never received
# the ALTER, so HogQL queries that join `ai_events` to `person` and rewrite
# `person.properties.email` -> `<table>.pmat_email` fail with
# `Identifier '__table5.pmat_email' cannot be resolved`.
#
# The Distributed engine does not compute the column value — it just needs the
# column declaration so the reference parses and is forwarded to the data
# cluster. Type is `String` (matching the non-nullable form emitted by
# `MaterializedColumn.type` when `is_nullable=False`).
#
# Migration 0240 also picks up the column for fresh environments via the
# updated `PERSON_AI_EVENTS_SHIM_SQL` (CREATE TABLE IF NOT EXISTS is a no-op
# on existing envs); this migration covers production envs where the shim
# already exists.

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE person ADD COLUMN IF NOT EXISTS pmat_email String",
        node_roles=[NodeRole.AI_EVENTS],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
