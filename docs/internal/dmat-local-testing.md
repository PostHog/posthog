# Dynamic property materialization (dmat) — local testing guide

This is the operator-facing checklist for standing up the dmat branch on a local
PostHog dev environment and verifying every piece of it end-to-end. Pair this
with `dmat-deployment.md` (the production runbook) and the dmat RFC. Every
command below assumes you are on the `aspicer/dmat_new` branch with a clean
working tree, inside the flox environment.

## 0. What we're verifying

The dmat system has four moving parts that must agree:

1. **Schema** — 100 `dmat_string_*` columns on `sharded_events`, `events`,
   `writable_events`, plus the recreated kafka tables/MVs that consume them.
2. **Slot model** — `MaterializedColumnSlot` rows in Postgres, with state
   transitioning `PENDING → BACKFILL → READY` (and optionally setting
   `compaction_target_slot_index` during compaction).
3. **Ingestion** — plugin-server's `MaterializedColumnSlotManager` loads slot
   config and writes `dmat_string_<idx>` columns into the Kafka payload for
   live events, using extraction logic that mirrors the SQL backfill mutation.
4. **Read path** — HogQL printer rewrites `properties.<name>` to read
   `dmat_string_<idx>` for slots in `READY` state, falling back to JSON
   extraction otherwise. The same `toFloat / toBool / toDateTime` wrapper that
   wraps `mat_*` columns wraps `dmat_*` columns — there is no separate read
   path for dmat.

The test plan exercises all four, with a helper script
(`bin/dmat-local-smoke.py`) that automates the slow steps.

## 1. Bring up the dev environment

```sh
./bin/start
```

Wait until plugin-server, Django, ClickHouse, Kafka and Temporal are healthy.
You can use the `mcp__phrocs__*` tools (or `mprocs` UI) to inspect logs.

## 2. Apply migrations

```sh
hogli django migrate                               # Postgres: 1126_*
hogli django migrate_clickhouse --plan             # confirm 0244 will run
hogli django migrate_clickhouse                    # apply 0244
```

After the ClickHouse migration:

- `sharded_events`, `events`, and `writable_events` should have
  `dmat_string_0..99` (`Nullable(String)`).
- The legacy typed columns (`dmat_numeric_*`, `dmat_bool_*`, `dmat_datetime_*`)
  should be gone.
- `kafka_events_json` and `events_json_mv` should have been recreated.

Verification SQL (run via `clickhouse client`):

```sql
SELECT name, type
FROM system.columns
WHERE database = currentDatabase()
  AND table = 'sharded_events'
  AND name LIKE 'dmat\\_%'
ORDER BY name;
-- expected: 100 rows, all `dmat_string_<i>` with type `Nullable(String)`,
-- nothing for numeric/bool/datetime.

SELECT count() FROM system.tables
WHERE database = currentDatabase() AND name IN ('kafka_events_json', 'events_json_mv');
-- expected: 2
```

## 3. Run the parity tests

These pin the SQL ↔ TypeScript ↔ HogQL coercion contract. If any of them fail,
something has drifted and the rest of the test plan will produce
hard-to-diagnose mismatches.

```sh
# SQL side — runs real ClickHouse mutations on inserted events.
hogli test posthog/temporal/tests/backfill_materialized_property/test_coercion_parity.py

# HogQL side — verifies dmat path matches JSON-fallback path for every property type.
hogli test posthog/hogql/transforms/test/test_property_types_dmat.py

# TypeScript side — same fixture, plugin-server extraction.
cd nodejs && pnpm test src/worker/ingestion/create-event.dmat.test.ts
```

All three must pass before continuing.

## 4. Run the helper script

`bin/dmat-local-smoke.py` (added by this guide) walks a single slot through
the full lifecycle. By default it:

1. Picks (or creates) a property definition on `team_id=1` with type `String`.
2. Sends a few `$pageview` events that include the property — these go through
   plugin-server using JSON only (no slot exists yet).
3. Creates the slot via the API (`assign_slot`) — slot starts in `PENDING`.
4. Sends another batch of events — still JSON-only since the slot is `PENDING`.
5. Runs `BackfillMaterializedPropertiesBatchWorkflow` directly via Temporal
   client (with `cache_refresh_wait_seconds=10` to keep the wait short).
6. Sends a final batch — now plugin-server should be writing `dmat_string_<idx>`
   on each event because the slot transitioned to `BACKFILL` then `READY`.
7. Runs HogQL `SELECT properties.<name> FROM events` and asserts the rendered
   ClickHouse SQL contains `dmat_string_<idx>`, not `JSONExtractRaw`.
8. Runs the same query on the older events (created before the slot existed)
   and asserts the values match — proves the historical backfill worked.

```sh
python bin/dmat-local-smoke.py --team-id 1 --property dmat_test_prop
```

If you want to test a specific phase manually, the script also accepts
`--phase` to run only one stage; see `--help`.

## 5. Manual verification steps

These check the parts the helper script can't easily assert.

### 5a. Slot lifecycle in Postgres

After step 4, run:

```sh
hogli django shell <<'PY'
from posthog.models import MaterializedColumnSlot
for s in MaterializedColumnSlot.objects.all():
    print(f"{s.id} team={s.team_id} prop={s.property_definition.name} "
          f"slot_index={s.slot_index} state={s.state} "
          f"compaction_target={s.compaction_target_slot_index} "
          f"run_id={s.backfill_temporal_run_id}")
PY
```

Expected: one row in `READY` with a non-null `slot_index` between 0 and 99
and `compaction_target_slot_index = NULL`.

### 5b. Plugin-server ingestion

After step 4, capture a Kafka message off `events_json` topic and inspect its
payload:

```sh
docker exec -it posthog-kafka-1 kafka-console-consumer \
  --bootstrap-server kafka:9092 --topic events_json --max-messages 1 \
  --property print.key=true --property print.headers=false
```

Expected JSON payload includes a `"dmat_string_<idx>": "<value>"` field
matching the slot's `slot_index` and the property value.

### 5c. ClickHouse-side verification

Verify both new and historical events have populated `dmat_string_<idx>`:

```sql
SELECT
    count(*) AS rows,
    countIf(dmat_string_0 IS NOT NULL) AS rows_with_dmat,
    sum(length(toString(dmat_string_0))) AS dmat_bytes
FROM events
WHERE team_id = 1 AND event = '$pageview'
  AND timestamp >= now() - INTERVAL 1 HOUR;
```

`rows_with_dmat` should equal `rows` (or close to it — events without the
property still write `NULL`, which is correct).

### 5d. HogQL via the UI

Open the SQL editor at `http://localhost:8000/project/1/sql` and run:

```hogql
SELECT properties.<your_test_property> AS p, count()
FROM events
WHERE timestamp >= now() - INTERVAL 1 HOUR
GROUP BY p
ORDER BY count() DESC
```

Click the "ClickHouse SQL" tab — the rendered SQL must reference
`events.dmat_string_<idx>`, not `JSONExtractRaw(events.properties, ...)`.

## 6. Test compaction

Compaction is the trickiest piece because it's only triggered when fewer
than `COMPACTION_FREE_COLUMN_THRESHOLD = 5` columns are free. For local testing,
we can either:

**Option A**: shrink the threshold temporarily to force a trigger:

```sh
hogli django shell <<'PY'
# Patches the constant in the running process — use this BEFORE triggering the workflow.
# Note: this only affects the Django shell process; the Temporal worker reads the constant
# at module-import time, so it picks up the lower threshold on its next workflow run.
import posthog.models.materialized_column_slots as mod
mod.COMPACTION_FREE_COLUMN_THRESHOLD = 95   # triggers compaction whenever we have
                                            # < 95 free columns (i.e. > 5 in use).
print(mod.COMPACTION_FREE_COLUMN_THRESHOLD)
PY
```

This won't propagate to the temporal worker — instead, set the constant by
editing `posthog/models/materialized_column_slots.py`, restarting the temporal
worker, then triggering the workflow.

**Option B**: fill the column pool with stub `READY` slots (clean, recommended):

```sh
python bin/dmat-local-smoke.py --phase fill-pool --slot-count 96
```

The script creates 96 stub `READY` slots (across 96 separate teams so per-team
uniqueness doesn't fight us), leaving 4 free columns — below the threshold of 5,
which will trigger compaction on the next workflow firing.

Then trigger the workflow:

```sh
python bin/dmat-local-smoke.py --phase trigger-workflow
```

In Postgres, every `READY` slot should now have a non-null
`compaction_target_slot_index` clustered in a small dense range. After the
mutation completes and `finalize_compaction` runs, `slot_index` is the new
target and `compaction_target_slot_index = NULL`.

## 7. Test the kill switch

```sh
# With the helper script having created a working slot:
redis-cli -h localhost set dmat_kill_switch 1

# Wait ~60s for the background refresher to pick it up
sleep 65

# Send a fresh event
python bin/dmat-local-smoke.py --phase send-events --count 1

# Verify dmat columns are NOT populated for the new event
clickhouse-client --query "SELECT dmat_string_<idx> FROM events
                           WHERE team_id = 1
                           ORDER BY timestamp DESC LIMIT 1"
# Expected: NULL

# HogQL queries should still work — they read existing dmat data unchanged.

# Re-enable
redis-cli -h localhost del dmat_kill_switch
sleep 65
```

## 8. Test retry from ERROR state

The simplest way is to deliberately fail a backfill. Easiest reproducer:

1. Create a slot via the API.
2. Trigger the workflow with an unreachable ClickHouse (e.g. stop the CH
   container while the mutation is running) — slot transitions to ERROR.
3. Hit the retry endpoint:

```sh
curl -X POST http://localhost:8000/api/environments/1/materialized_column_slots/<slot_id>/retry_backfill/
```

Slot should be back in `PENDING` with `slot_index = NULL` and
`error_message = NULL`.

## 9. Cleanup between runs

```sh
python bin/dmat-local-smoke.py --phase cleanup
```

Drops every `MaterializedColumnSlot`, but does NOT clear the columns
themselves — the data stays in `sharded_events` and is harmless (no slot
references it). Compaction would reclaim the columns later if you wanted to
reuse the indexes.

## What this plan does NOT cover

- **Production-scale mutation duration** — you can't measure 25B-row
  mutation time on a local box. Stage that on staging per
  `dmat-deployment.md` step 5.
- **Multi-shard behavior** — local ClickHouse is single-shard.
  `AlterTableMutationRunner.run_on_shards` becomes a no-op-on-single-shard;
  staging is the place to verify shard fanout.
- **Migration ordering between Django and plugin-server pods** — both restart
  in lock-step locally. The sequencing concerns in `dmat-deployment.md`
  ("Deployment ordering") only matter in CD pipelines.
