# DMAT branch review

Branch: `aspicer/dmat_new` (vs `origin/master`)

What follows is a coherence/consistency pass plus an honest list of where the
implementation drifted from the RFC and where the defensive code still hides
real bugs that should fail loud.

## Summary

The branch holds together. The four moving parts (schema, slot model, ingestion,
read path) agree with each other and with the dmat RFC's intent. The biggest
deviation from the RFC text is **string-only columns + read-time type wrappers**
(see `Deviations from spec` below) — and that change is a strict improvement that
brings dmat into parity with the existing `mat_*` system: they share the HogQL
read path now (same `PrintableMaterializedColumn`, same `_field_type_to_property_call`
type wrapper), only the write path differs (plugin-server + ALTER TABLE UPDATE
mutation for dmat, vs ClickHouse-side `MATERIALIZED` expression for `mat_*`).

The coercion contract between the three string-extraction paths
(SQL backfill mutation, HogQL JSON fallback, plugin-server live ingest) is pinned
by a shared fixture (`coercion_fixtures.json`) plus three parity tests — that is
the load-bearing invariant for the whole design and it is well-tested.

The deployment doc (`docs/internal/dmat-deployment.md`) is honest about its gaps
and matches what is actually in the code.

I added two new files:

- `docs/internal/dmat-local-testing.md` — manual test plan
- `bin/dmat-local-smoke.py` — automation script for the slow stages

## Deviations from spec (and whether they make sense)

### 1. String-only column pool — **agrees with the deployment doc, deviates from the RFC's `Schema` section**

**RFC says:** "string-only" but lists numeric/bool/datetime as future work.
**Implementation:** _strictly_ string-only. The legacy typed columns
(`dmat_numeric_*`, `dmat_bool_*`, `dmat_datetime_*`) are dropped in
`0249_add_dmat_string_columns_10_99.py`. The slot model's `property_type` field
is removed in migration `1144_*`. HogQL uses the same `Nullable(String)` →
`toFloat`/`toBool`/`toDateTime` wrapper that normal `mat_*` columns use.

**Verdict:** ✅ Strict improvement. Reuses the existing read path (the user's
explicit guidance: "we want to use the same pathways for reading with the same
casting"). Cleaner storage shape (Nullable means we don't need the `nullIf` wrap
that the legacy `mat_*` path has TODO'd to remove).

### 2. Compaction packs into a small dense range, not necessarily exactly 5 columns

**RFC says:** "consolidates all existing assignments into 5 dense columns"
**Implementation:** packs into the smallest possible dense range subject to the
per-team uniqueness invariant. If a team has 5 slots, that team alone needs 5
distinct columns, so 5 is a floor, not a ceiling. In practice the planner uses
a greedy first-fit walk and the resulting span is typically much smaller than
the slot count when teams have ≤ 1 slot each.

**Verdict:** ✅ Sensible. Matches the RFC's intent ("5 dense columns" was a
simplification). The test `test_compaction_triggers_when_free_columns_drop_below_threshold`
asserts the target span is `≤ max(5, len(slots) // 10)`.

### 3. Mutation chunking — defensive cap on `multiIf` branches

**RFC says:** "single combined mutation".
**Implementation:** `_chunk_assignments_by_branch_count` splits at column
boundaries when the total branch count exceeds `MAX_MULTIIF_BRANCHES_PER_MUTATION = 500`.
A single column with > 500 branches is submitted as its own chunk (we never
split a `multiIf` mid-column because the multiIf is self-contained).

**Verdict:** ✅ Pragmatic. The chunking comment correctly notes ClickHouse's
~256 KiB `max_query_size` is the binding constraint. The deployment doc's
"Mutation-too-large is detected, but a single oversized column isn't split"
gap is correctly called out.

### 4. Activity heartbeating during long mutations

**RFC says:** "polls `system.mutations`".
**Implementation:** `HeartbeaterSync` background thread + `AlterTableMutationRunner`
which polls `system.mutations` per replica until `is_done=1`.

**Verdict:** ✅ Required for activity timeouts at production scale. Workflow
`heartbeat_timeout=5min`, activity `start_to_close_timeout=12h`. Heartbeat
interval is `heartbeat_timeout / 12`.

### 5. Stranded-slot detection but no auto-recovery

**RFC says nothing about stranded slots**.
**Implementation:** `assign_pending_slots` distinguishes
"BACKFILL slots from this run" (reclaimed automatically — handles activity
retries) from "BACKFILL slots from a prior run" (logged + Sentry alert,
operator must reset to PENDING).

**Verdict:** ✅ Correct. Auto-recovering stranded slots is unsafe — we can't
tell whether their mutation completed.

### 6. Crash recovery between mutation completion and `finalize_compaction` swap

This is openly noted in the deployment doc as a known gap. Slots stay correctly
dual-written (HogQL keeps reading the old column, ingestion keeps writing both)
but won't auto-finalize on the next run because the `compaction_target_slot_index`
filter excludes them. Operator runs `finalize_compaction` manually.

**Verdict:** ⚠️ Acceptable for v1; harmless to data. Long-term fix in
`Long-term fix:` comment in the doc.

## Defensive patterns that shouldn't be defensive

The user's instruction was: fail-fast unless we explicitly want to fall back to
JSON extraction for a single broken slot. The patterns below either swallow
errors or default values where I'd argue the system should fail loud.

### A. `posthog/api/materialized_column_slot.py:32-37` — `get_auto_materialized_property_names`

```python
try:
    materialized_columns = get_materialized_columns("events")
    return {col.details.property_name for col in materialized_columns.values()}
except Exception as e:
    logger.warning("Failed to get auto-materialized columns", error=str(e))
    return set()
```

**Concern:** swallows ANY exception and returns an empty set. The empty set is
used to filter properties in the "available to materialize" list — when this
fails, properties already covered by `mat_*` show up as available, so a user
could waste a dmat slot on a property already auto-materialized. Not unsafe,
but masks a real misconfiguration.

**Recommendation:** let the exception propagate. If `get_materialized_columns`
fails we want to know — it's the same call HogQL itself uses for query rewriting,
and a silent failure here may correlate with a broader problem.

### B. `posthog/api/materialized_column_slot.py:142-169` — `auto_materialized` action

Wraps the whole action in `try/except Exception` and returns 500 on any error.
This is standard DRF-ish behavior, but the message "An internal error has
occurred" hides the real exception from the operator's UI. The HogQL/`get_materialized_columns`
result is cached and pure — the only realistic failure is misconfiguration.

**Recommendation:** drop the catch-all. DRF will turn unhandled exceptions into
500s anyway, with the actual traceback available to staff in error reporting.

### C. `nodejs/src/utils/dmat-kill-switch.ts` — Redis errors silently swallowed during init

```ts
void this.refresher.get().catch((error) => {
  logger.error('DmatKillSwitch: failed to initialize', { error })
})
```

**Concern:** if Redis is unreachable at startup, the kill switch defaults to
"enabled" (i.e. ingestion runs) without surfacing the error to the health check.
Long-term this is the right call (we don't want a Redis blip to kill ingestion
globally), but a never-once-reached Redis state should probably be visible.

**Recommendation:** maybe expose a `lastSuccessfulRefreshAt` for the health
endpoint to inspect, so an operator can tell "kill switch is operational" vs
"kill switch has never seen a successful refresh and is silently fail-open".
Low-priority — the cost of action here is configuration noise.

### D. `nodejs/src/utils/materialized-column-slot-manager.ts` — postgres failures propagate

This is **not defensive** today: a Postgres error in `getSlots` propagates up,
`createEventStep` rejects, the whole event fails to ingest. That is fail-fast
to the point of being too aggressive — a transient Postgres blip would drop
real events.

**Recommendation (judgment call):** wrap `lazyLoader.get()` in a try/catch and
return `[]` on Postgres error, with a counter increment + a Sentry capture.
The fallback (no dmat column written, HogQL serves from JSON) is correct, just
slow. Today this is fail-fast in the wrong direction — losing the event entirely
is worse than serving the property via JSON for the duration of the outage.

**Counter-argument:** if you want strict fail-fast at the consumer level so that
ingestion-pipeline retries handle the blip, leave it. I'd ask a real ingestion
oncall before deciding. Either way: should be deliberate, not accidental.

### E. `posthog/models/materialized_column_slots.py:137-156` — `prevent_property_type_changes_with_materialized_slots`

After the move to string-only columns, this guard is over-protective: HogQL
applies the type wrapper at read time, so a property changing from String →
Numeric while a dmat slot exists is fine — `toFloat("42")` parses, `toFloat("hello")`
returns NULL. The guard's docstring still says "values would silently start
failing to parse", which is now incorrect for dmat slots specifically (it remains
correct for legacy typed `mat_*` columns).

**Recommendation:** scope the guard to legacy typed materialized columns, or
drop it entirely now that dmat is string-only. Today it just prevents an
operation that would otherwise work.

## Cross-cut consistency: SQL ↔ TypeScript ↔ HogQL fallback

This is the load-bearing invariant. Three code paths must agree:

- **SQL backfill:** `posthog/temporal/backfill_materialized_property/activities.py:62`
  `_generate_property_extraction_sql()`
- **HogQL JSON fallback:** `posthog/hogql/printer/base.py:1540`
  `_unsafe_json_extract_trim_quotes()`
- **TypeScript live ingest:** `nodejs/src/worker/ingestion/create-event.ts:179`
  `jsonExtractRawAndTrimQuotes()`

All three are pinned by `posthog/temporal/backfill_materialized_property/coercion_fixtures.json`,
loaded by:

- `posthog/temporal/tests/backfill_materialized_property/test_coercion_parity.py`
  (SQL — runs real CH mutations)
- `posthog/hogql/transforms/test/test_property_types_dmat.py::TestDmatExtractionConsistency`
  (HogQL dmat-vs-JSON via execute_hogql_query)
- `nodejs/src/worker/ingestion/create-event.dmat.test.ts`
  (TypeScript live ingest)

I confirmed the SQL-side and TS-side paths produce byte-identical output for
every fixture case I walked through manually, including the awkward ones
(empty string, the literal string "null", JSON object value).

The HogQL printer's read-time wrap matches the dmat write-time format:

- dmat is `Nullable(String)` → printer skips the `nullIf(nullIf(col, ''), 'null')`
  wrap (because Nullable handles SQL NULL natively)
- `mat_*` is `String` (non-nullable) → printer applies the nullIf wrap
- Both then go through `_field_type_to_property_call` for type casting

## Test coverage

| Layer                                  | Test file                                                                                                     | Status                                             |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| Slot model + constraints               | `posthog/api/test/test_materialized_column_slot.py`                                                           | rewritten for PENDING flow                         |
| Activity logging                       | `posthog/api/test/test_materialized_column_activity_logging.py`                                               | exercises every state transition                   |
| Plan / pack                            | `posthog/temporal/tests/backfill_materialized_property/test_batched_activities.py::TestPlanColumnAssignments` | covers per-team uniqueness + determinism           |
| Build SQL command                      | same file, `TestBuildBatchedUpdateCommand`                                                                    | parameterizes property names (SQL-injection guard) |
| Activities, including reclaim/stranded | same file, `TestAssignPendingSlots`                                                                           | reclaim same-run + ignore other-run                |
| Compaction E2E                         | same file, `TestCompaction`                                                                                   | trigger threshold + finalize swap                  |
| Workflow happy path + rollback         | `test_batched_workflow.py`                                                                                    | Temporal time-skipping environment                 |
| TS slot manager                        | `nodejs/src/utils/materialized-column-slot-manager.test.ts`                                                   | kill switch + team isolation                       |
| TS kill switch                         | `nodejs/src/utils/dmat-kill-switch.test.ts`                                                                   | fail-open default + Redis flip                     |
| TS ingest                              | `nodejs/src/worker/ingestion/create-event.dmat.test.ts`                                                       | dual-write during compaction                       |
| HogQL dmat                             | `posthog/hogql/transforms/test/test_property_types_dmat.py`                                                   | dmat-vs-JSON parity for every type                 |
| Coercion parity                        | `posthog/temporal/tests/backfill_materialized_property/test_coercion_parity.py`                               | SQL-side fixture-driven                            |

Coverage gaps that the deployment doc already calls out:

- No real-ClickHouse integration test for the **batched** mutation. The
  per-slot legacy mutation has one; the new batched one is mocked everywhere.
  The plan is to validate on staging.
- No multi-shard test (local CH is single-shard).
- Frontend kea-typegen file isn't committed (pre-existing).

## Files I added in this review

- `docs/internal/dmat-local-testing.md` — manual test plan (mirrors deployment
  doc style)
- `bin/dmat-local-smoke.py` — phased automation: bootstrap, send events,
  trigger workflow, fill pool to force compaction, cleanup. Default phase is
  `full`, which runs the entire happy path and asserts both the historical
  backfill and the live-ingest dual-write produced rows in the column.

Run via:

```sh
python bin/dmat-local-smoke.py --team-id 1 --property dmat_test_prop
```

## What I would NOT change without more discussion

- **Mutation chunking strategy.** Splitting at column boundaries is correct
  (each multiIf is self-contained), and the cap is conservative. I'd validate
  on staging before tuning.
- **Compaction-target NULL on swap.** The current finalize sets
  `compaction_target_slot_index = NULL` and moves `slot_index ← target`. An
  alternative ("don't blank the target, just mark a different state") would
  be more debuggable but adds another transition; I think the current shape
  is right for v1.
- **Schedule task queue (`settings.TEMPORAL_TASK_QUEUE`).** In production this
  resolves to `general-purpose-task-queue`, where the workflow is registered.
  Locally it's `development-task-queue`. Both work. Don't override unless
  there's a deployment reason.
