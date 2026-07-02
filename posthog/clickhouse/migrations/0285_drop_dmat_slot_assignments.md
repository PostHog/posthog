# Runbook: finish removing the dmat ClickHouse schema (manual, ClickHouse team)

Migration `0285_drop_dmat_slot_assignments` drops the standalone `dmat_slot_assignments`
dictionary and table automatically. It deliberately does **not** drop the `dmat_string_0..9`
columns from the events tables, because:

- A `DROP COLUMN` must be initiated by the ClickHouse team directly on the cluster — it can
  stall and block releases — and only then does a matching `DROP COLUMN` migration land
  (see `.claude/skills/clickhouse-migrations`).
- The columns are still SELECTed by the events materialized views, so the MVs must be
  recreated without them first.
- One of those MVs, `events_json_ws_mv` (with `kafka_events_json_ws`), is a no-go zone: its
  live schema carries environment-specific `mat_*` columns that are **not** in this repo, so
  it cannot be recreated from repo SQL.

The `dmat_string_*` columns are nullable and have only ever held NULL (the populate path was
never enabled in production), so this cleanup is not urgent and can run in a low-traffic window.

## Where the columns live

Added by applied migrations `0179` (sharded_events, events — DATA) and `0232` (writable_events —
INGESTION_EVENTS), and threaded through the kafka tables + MVs via the (now dmat-free) templates.

## Manual steps, per region (dev → US → EU)

1. **Recreate the MSK events MV without dmat.** Drop `events_json_mv` and recreate it from the
   current `EVENTS_TABLE_JSON_MV_SQL()` template (which no longer selects `dmat_string_*`).
   This briefly pauses MSK → `writable_events` projection; do it in a low-traffic window.

2. **Recreate the WS events MV without dmat — NO-GO ZONE, hand-crafted.** Do **not** apply repo
   SQL. Capture the live `events_json_ws_mv` definition, remove only the `dmat_string_*` columns
   from its SELECT (and `kafka_events_json_ws` if it declares them), and recreate preserving
   every environment-specific `mat_*` column. Verify against the live def before and after.

3. **Drop the columns** once no MV references them, on every node role that has them:

   ```sql
   ALTER TABLE writable_events DROP COLUMN IF EXISTS dmat_string_0, ... , DROP COLUMN IF EXISTS dmat_string_9;
   ALTER TABLE sharded_events  DROP COLUMN IF EXISTS dmat_string_0, ... , DROP COLUMN IF EXISTS dmat_string_9;
   ALTER TABLE events          DROP COLUMN IF EXISTS dmat_string_0, ... , DROP COLUMN IF EXISTS dmat_string_9;
   ```

   Watch the mutation/distribution queues between tables.

4. **Land the matching migration.** After the columns are gone everywhere, open a follow-up
   migration containing the same `DROP COLUMN` statements (cloud-no-op + this same runbook for
   any region not yet done) so the codebase schema stays in sync, and remove `0179`/`0232`'s
   inlined `_add_dmat_string_columns` once no fresh cluster needs them.

## Abort

Steps 1–3 are independent per table; if step 2 looks wrong on the live WS MV, stop — the columns
are harmless dormant NULLs, so leaving them in place is safe.
