# DMAT branch — what the code actually does

Branch: `aspicer/dmat_new` vs `origin/master`. Six commits, ~4.7k LOC added across
ClickHouse schema, Postgres schema, Django model + API, a new Temporal workflow,
plugin-server (`nodejs/`), HogQL, and the frontend slot management page.

This is a plain-English description of the moving parts so it can be cross-checked
against the dynamic property materialization (dmat) RFC. Not a review — for that see
`DMAT_REVIEW.md`.

---

## 1. The big picture

Dmat lets an operator pick custom event properties to be materialized into dedicated
ClickHouse columns, so HogQL stops having to scan the JSON `properties` blob to read
them. Unlike PostHog's existing auto-materialized `mat_*` columns (which are populated
by ClickHouse's own `MATERIALIZED` expression), dmat columns are populated from
**outside** ClickHouse:

- **Live events**: plugin-server (Node) extracts the property at ingest time and
  writes it directly into the right `dmat_string_<idx>` column on the Kafka payload.
- **Historical events**: a weekly Temporal workflow runs an `ALTER TABLE UPDATE`
  mutation that backfills every selected property in a single combined statement.

The pool is **string-only**: every dmat column is `Nullable(String)`. HogQL applies
the same `toFloat` / `toBool` / `toDateTime` wrapper at query time that it already
applies to the legacy `mat_*` columns, so the read path is shared with the existing
materialized-column system. The only thing dmat owns is the _write_ path.

A column index pool of **100 columns** lives in ClickHouse. A team can hold up to
**5 slots**. When fewer than 5 free columns remain across the whole pool the workflow
runs **compaction**: it dual-writes every active slot into a smaller dense range and
swaps once the mutation is done, freeing the rest of the pool for new sign-ups.

---

## 2. Schema

### ClickHouse (`posthog/models/event/sql.py`, migration `0244`)

- Replaces the four typed pools (`dmat_string_*`, `dmat_numeric_*`, `dmat_bool_*`,
  `dmat_datetime_*`, 10 columns each) with a single string pool sized at
  `DMAT_STRING_COLUMN_COUNT = 100`.
- Migration `0244` is the interesting one: it drops the JSON kafka tables and the
  feeding MVs, ALTERs `sharded_events` / `events` / `writable_events` to add
  `dmat_string_10..99`, drops the legacy typed columns (which were never wired to
  the kafka MV on master, so they had no data), then recreates the kafka tables and
  MVs from the updated schema. The recreate is mandatory because the MV's `SELECT`
  enumerates every dmat column from `MV_DYNAMICALLY_MATERIALIZED_COLUMNS()` and the
  kafka table's column list is fixed at CREATE time.
- Cloud-only WarpStream path is forked off via the existing `_is_cloud` switch; same
  shape as migration `0232`.

**Where this can hurt**: between dropping the MV/kafka tables and recreating them
(steps 1 and 4 of `0244`), new events sit in Kafka and are not consumed. This is
called out in the deployment doc — operators are told to run during a low-traffic
window.

### Postgres (`posthog/models/materialized_column_slots.py`, migration `1126`)

`MaterializedColumnSlot` rows describe one (team, property) → column-index assignment.
Migration `1126` folds three changes into one because none have shipped:

- New `PENDING` state (default). `slot_index` is now nullable, valid range expanded
  to 0..99.
- New `compaction_target_slot_index` field for the dual-write swap.
- Removes `property_type` (the pool is string-only — type info lives on the
  `PropertyDefinition` and HogQL applies the cast at read time).

The model carries the load-bearing constraints:

- `unique_team_property_definition`: a property can only have one slot per team.
- `unique_team_slot_index` _(partial: `slot_index IS NOT NULL`)_: per-team, the
  assigned column index is unique. Different teams **can** share an index — the
  mutation discriminates by `team_id` in its `multiIf` branches.
- `unique_team_compaction_target` _(partial)_: same uniqueness rule for the
  compaction target — a defense-in-depth check against a planner regression.
- `valid_slot_index` and `slot_index_required_when_assigned` enforce the lifecycle:
  PENDING/ERROR may have NULL `slot_index`, BACKFILL/READY must have one assigned.

A `pre_save` signal on `PropertyDefinition` blocks changing `property_type` while
any slot exists for it — see Gotchas.

---

## 3. The PENDING → BACKFILL → READY lifecycle

Defined in `MaterializedColumnSlotState`:

| State    | What it means                                                                   | Plugin-server | HogQL reads from                                      |
| -------- | ------------------------------------------------------------------------------- | ------------- | ----------------------------------------------------- |
| PENDING  | Queued. No column assigned yet.                                                 | Ignores it    | JSON fallback                                         |
| BACKFILL | Has a column. Ingestion writes new events; historical mutation in flight.       | Writes        | JSON fallback (still — to avoid serving partial data) |
| READY    | Backfill done.                                                                  | Writes        | The dmat column                                       |
| ERROR    | Backfill failed; operator can call `retry_backfill` to push it back to PENDING. | Ignores       | JSON fallback                                         |

Compaction adds a sub-state: `compaction_target_slot_index` is populated on a READY
slot while it is being repacked. Plugin-server dual-writes; HogQL keeps using the
old column until the workflow finalizes the swap.

---

## 4. The Django API (`posthog/api/materialized_column_slot.py`)

`MaterializedColumnSlotViewSet` is staff-only, scope `INTERNAL`. Endpoints:

- `GET /slot_usage` — `{used_total, available, max_slots_per_team}` for the team.
- `GET /available_properties` — properties eligible for materialization. Filters out
  PostHog system props (anything starting with `$` except `$feature/`), props with
  no `property_type`, props already auto-materialized by `mat_*`, and any property
  that already has a slot.
- `GET /auto_materialized` — what PostHog has auto-materialized as `mat_*`. Used
  only to show "you can't materialize this — already done" on the UI.
- `POST /assign_slot` — creates a slot in PENDING with `slot_index = NULL`. The
  validation runs inside a `select_for_update` on the property definition and a fresh
  read of the team's slots, so concurrent calls hitting the 5-slot cap can't race.
  Returns 409 on `IntegrityError` (constraint collision).
- `DELETE /<id>` — refuses to delete a BACKFILL slot (a mutation is in flight against
  its column). PENDING/READY/ERROR may be deleted at any time. Logs to ActivityLog.
- `POST /<id>/retry_backfill` — only valid for ERROR slots. Resets to PENDING with
  a fresh `slot_index = NULL` so the next workflow run packs it into whichever
  column is freshest.

**Code reuse**: `get_materialized_columns("events")` is the same cached call HogQL
itself uses for its `mat_*` rewrites — same 15-minute TTL, no extra ClickHouse traffic.

---

## 5. The Temporal workflow (`posthog/temporal/backfill_materialized_property/`)

Two workflows are registered:

- **Legacy `BackfillMaterializedPropertyWorkflow`** — the per-slot one that already
  existed. Kept registered for backwards compatibility with already-running
  instances; the API no longer launches new ones.
- **New `BackfillMaterializedPropertiesBatchWorkflow`** — the weekly batched
  workflow. A single Temporal cron schedule (`weekly-dmat-backfill`, Sunday 00:00
  UTC, `ScheduleOverlapPolicy.SKIP`) fires it. The schedule is registered manually
  via `create_or_update_weekly_dmat_backfill_schedule` from a Django shell — it is
  **not** wired into worker startup. (Worth flagging: this is easy to forget on a
  fresh environment.)

The workflow runs four activities in order:

### 5.1 `assign_pending_slots`

Runs in a single Postgres transaction with `select_for_update`. Reads three sets of
slots:

- **PENDING** slots — the new work for this cycle.
- **BACKFILL slots claimed by _this_ `workflow_run_id`** — reclaimed automatically.
  This handles the case where the Postgres commit succeeded but Temporal lost
  the activity completion ack and retried; without reclaim those slots would sit
  in BACKFILL forever.
- **BACKFILL slots from _other_ run IDs** — _not_ reclaimed (we can't know whether
  the prior mutation completed). Logged + Sentry alert; the deployment doc tells
  the operator to manually flip them to PENDING.

If free columns drop below `COMPACTION_FREE_COLUMN_THRESHOLD = 5`, every READY slot
without a target gets a `compaction_target_slot_index` populated by
`_plan_compaction_targets`.

The two planners (`_plan_column_assignments` for new PENDING slots,
`_plan_compaction_targets` for repacks) share the same per-team uniqueness rule and
both walk slots in deterministic `(team_id, id)` order — important for activity
retry idempotency. The compaction planner is best-effort: any slot it can't fit
(per-team uniqueness can't be honored) is silently skipped and re-evaluated next
week. A Sentry alert fires if any slots are skipped, since sustained skipping means
the pool isn't recovering.

Output is `AssignPendingSlotsResult` with three lists:
`assignments` (column → branches), `assigned_slot_ids` (PENDING → BACKFILL +
reclaimed), and `compacted_slot_ids` (READY slots with a fresh target).

The slot stamps the per-execution **run_id** into `backfill_temporal_run_id`. The
schedule reuses the same workflow_id every week, so workflow_id alone wouldn't
distinguish "this firing's commits" from "last week's"; run_id is unique per
execution and stable across activity retries.

### 5.2 Cache wait (3 minutes)

`workflow.sleep(180s)`. Before submitting the historical mutation, the workflow
sleeps for the plugin-server slot-cache refresh window (`TEAM_AND_SLOTS_REFRESH_AGE_MS`
plus `TEAM_AND_SLOTS_REFRESH_JITTER_MS` plus buffer = 2.5 min worst case + 30 s safety).
By the time the mutation runs every plugin-server is already writing to the new
columns — no gap between "mutation completes" and "queries see the column". The
3-min constant lives in `nodejs/src/utils/lazy-loader.ts` with a comment pointing
back to the workflow.

### 5.3 `run_batched_mutation`

Builds the SQL via `_build_batched_update_command`. Each affected column gets a
`multiIf(team_id = X, extract_for_X, team_id = Y, extract_for_Y, ..., col_name)`
expression — the trailing `col_name` keeps the existing value for unaffected rows
(zero-cost no-op). Property names are passed as **parameters** keyed
`prop_<slot_uuid_no_dashes>` so collision-free across the whole mutation; team_ids
are inlined as integer literals (safe — typed `PositiveSmallIntegerField`).

**Chunking**: `_chunk_assignments_by_branch_count` splits at column boundaries when
total branches exceed `MAX_MULTIIF_BRANCHES_PER_MUTATION = 500`. The split is at
column boundaries because a `multiIf` is self-contained per column. A single column
with > 500 branches lands in its own chunk and is submitted with a logged warning
(it may individually exceed the cap — no auto-split inside a column, called out as
a known gap).

Submission goes through `AlterTableMutationRunner` (idempotent: re-running the same
command attaches to the existing mutation rather than queueing a duplicate) and
polls `system.mutations` per replica until `is_done = 1`. The activity is `sync` and
can run for hours, so it's wrapped in `HeartbeaterSync` — a context manager that
spawns a background thread heartbeating Temporal at `heartbeat_timeout / 12`
(workflow sets `heartbeat_timeout=5min`, `start_to_close_timeout=12h`).

### 5.4 `activate_slots` and `finalize_compaction`

After the mutation, two parallel finalization steps:

- `activate_slots`: BACKFILL → READY for `assigned_slot_ids`, plus per-slot activity
  log entry.
- `finalize_compaction`: in a single transaction with `select_for_update`, swap
  `slot_index ← compaction_target_slot_index` and clear the target. Inside the
  transaction it re-checks per-team uniqueness against _other_ slots — if some
  operator hand-edited the table or a planner bug let two slots claim the same
  target, the whole batch aborts before any swap is committed.

### 5.5 Failure path

If the mutation fails, the workflow runs `fail_slots` (BACKFILL → ERROR with the
exception message) on the assigned slots and `clear_compaction_targets` (NULL the
target) on the compacted slots. Compacted slots stay READY on their original column
— no data loss; the cancelled new column is freed.

---

## 6. Plugin-server (`nodejs/`)

### 6.1 Slot configuration loader (`utils/materialized-column-slot-manager.ts`)

A `LazyLoader<MaterializedColumnSlot[]>` keyed by `team_id`. TTL is shared with
`TeamManager` (2 min ± 30 s) — the same constants the workflow's 3-minute wait is
calibrated against.

Loads only `state IN ('READY','BACKFILL')` and `slot_index IS NOT NULL` rows. Joins
`posthog_propertydefinition` to pick up `property_name` (the slot table only stores
the FK).

If a `DmatKillSwitch` is wired in, every `getSlots*` call short-circuits to `[]`
when the switch is on — the rest of the pipeline already does nothing when the slot
list is empty, so the kill switch cascades through with no per-event branch.

### 6.2 Kill switch (`utils/dmat-kill-switch.ts`)

Mirrors the existing `EventIngestionRestrictionManager` pattern. A
`BackgroundRefresher<boolean>` polls Redis (key `dmat_kill_switch`, anything
non-empty = disabled) every 60 s. `isDisabled()` is sync and hot-path-safe. Default
on Redis failure is **enabled** (fail-open) — the alternative would silently kill
all dmat ingestion every time Redis hiccups.

### 6.3 Pipeline wiring

Three pieces:

1. **Prefetch** (`event-processing/prefetch-dmat-slots-step.ts`): a batch step in
   `post-team-preprocessing-subpipeline` that fires-and-forgets a single
   `getSlotsForTeams` call for every team in the batch, collapsing N per-event
   Postgres lookups into one when the cache is cold.
2. **Per-event lookup** (`event-processing/create-event-step.ts`): the existing step
   now takes the slot manager and calls `getSlots(teamId)` per event. Cache is warm
   from the prefetch.
3. **Extraction** (`worker/ingestion/create-event.ts`): `extractDynamicMaterializedColumns`
   walks the slot list, pulls each property out of the event, runs the
   plugin-server-side `jsonExtractRawAndTrimQuotes` (mirrors the SQL extraction
   exactly), and stores the result on `processedEvent.dmat_columns` keyed by column
   name. During compaction, both `slot_index` and `compaction_target_slot_index`
   columns are written with the same value.
4. **Serialization** (`event-processing/emit-event-step.ts`): `serializeEvent`
   spreads `event.dmat_columns` directly into the Kafka payload. The kafka
   table's column list is fixed (recreated by migration `0244`), so unknown JSON
   keys would be dropped — this is why both schema and code must be deployed in
   the right order.

The slot manager is added to `Hub` and constructed in `utils/db/hub.ts`. Every
analytics pipeline (event subpipeline, joined pipeline, per-distinct-id pipeline,
error tracking pipeline + their `testing-` variants) plumbs it through.

### 6.4 The cross-language coercion contract — load-bearing

Three code paths must produce byte-identical strings for the same input:

- **SQL backfill** mutation: `_generate_property_extraction_sql` →
  `replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, %(name)s), ''), 'null'), '^"|"$', '')`
- **HogQL JSON fallback**: `_unsafe_json_extract_trim_quotes` in `printer/base.py`
  uses the same SQL.
- **Plugin-server live ingest**: `jsonExtractRawAndTrimQuotes` in `create-event.ts`
  re-stringifies the parsed JS value and applies the same nullIf + quote-trim rules.

All three are pinned by the shared
`posthog/temporal/backfill_materialized_property/coercion_fixtures.json` fixture and
exercised by parity tests on each side. This is the single most important invariant
in the system: if the three paths disagree, the same row reads differently before
vs after backfill.

---

## 7. HogQL (`hogql/transforms/property_types.py`, `printer/base.py`)

`build_property_swapper` annotates each property reference with the dmat column name
when a slot exists (`prop_info["dmat"] = f"dmat_string_{slot.slot_index}"`).
Critically, the AST is **not** rewritten in place — the swapper falls through to
`_field_type_to_property_call`, which wraps the field reference with the
property-type wrapper (`toFloat` / `toBool` / `toDateTime`). The printer's
`_get_dmat_column_name` substitutes the column when it visits the wrapped node.
Result: dmat shares the **identical** read path as `mat_*` columns. The dmat column
being `Nullable(String)` (rather than `mat_*`'s plain `String`) means the printer
can skip the `nullIf(nullIf(col, ''), 'null')` wrap — Nullable handles SQL NULL
natively.

---

## 8. Frontend (`scenes/data-management/MaterializedColumns/*`)

Modest update on top of the existing slot management page:

- New PENDING state with a "awaiting next weekly cycle" caption when `slot_index` is
  null.
- Renders `dmat_string_<idx>` as the column name (the previous code branched on
  `property_type` and would `throw new Error` for unknown types — now obsolete and
  removed).
- During compaction, shows the `current → target` arrow with a tooltip explaining
  the dual-write.
- `retrySlot` action posts to the new `retry_backfill` endpoint and toasts the
  outcome.
- `slotUsage` shape changed from per-type breakdown to flat
  `{used_total, available, max_slots_per_team}`.

---

## 9. Things to double-check against the spec

These are the areas most likely to drift from the RFC:

### Looks good

- **Coercion parity contract** is well-pinned by shared fixture + tests on each
  side.
- **Activity heartbeating** is correct for hours-long mutations.
- **Stranded-slot detection vs reclaim**: the right call to auto-reclaim only the
  current run's slots and surface the rest to ops.
- **Compaction transactional finalize** with intra-tx uniqueness re-check is exactly
  the right shape — fails loudly rather than corrupting on a planner regression.
- **String-only pool** is a strict improvement over the RFC's typed pool — shares
  the read path with `mat_*` and avoids the schema change cost of adding new typed
  pools later.

### Potentially needs work / look here first

1. **Schedule registration is manual.** `create_or_update_weekly_dmat_backfill_schedule`
   is not called from worker startup. A fresh production environment will silently
   never run the workflow until someone runs the function from a Django shell.
   Consider auto-registering on worker startup (with the existing
   `ScheduleOverlapPolicy.SKIP` it's safe to re-register).
2. **Single-column chunk overflow** is logged but not split. If MAX*SLOTS_PER_TEAM
   and team count combine to put > 500 branches on one column the mutation may
   exceed `max_query_size`. Currently bounded by 100 columns × 5 slots = 500
   theoretical max per column, so this is \_just* under the line. Tightening either
   constant requires revisiting.
3. **Crash between mutation completion and `finalize_compaction`** is openly
   documented as a v1 gap (deployment doc). Slot stays correctly dual-written, but
   the swap doesn't auto-finalize — operator must run the activity manually.
4. **`prevent_property_type_changes_with_materialized_slots` signal** is now
   over-protective: with string-only columns, `toFloat("42")` parses fine and
   `toFloat("hello")` returns NULL — a property type change is no longer a data
   issue for dmat slots. The guard's docstring still claims values would silently
   fail to parse. Either drop the guard or scope it to legacy `mat_*`.
5. **`get_auto_materialized_property_names` swallows exceptions** and returns an
   empty set. If ClickHouse misconfiguration takes the call down, a user could
   waste a slot on a property that's already covered by `mat_*`. Not unsafe; masks
   misconfiguration.
6. **`auto_materialized` action has a catch-all 500.** Returns
   `"An internal error has occurred"` instead of letting DRF surface the trace.
7. **Plugin-server slot fetch failure aborts the event.** A Postgres blip while
   loading slots rejects the event from `createEventStep`. In an outage you'd
   prefer to fall back to JSON (slow but correct) rather than drop events. Decide
   whether fail-fast or fail-open is right with an ingestion oncall.
8. **Kill switch on Redis startup failure** is silently fail-open. Probably right;
   may want a `lastSuccessfulRefreshAt` exposed to the health endpoint.
9. **No real-CH integration test for the batched mutation.** The per-slot legacy
   mutation has one; the new batched one is mocked everywhere. Plan is to validate
   on staging.
10. **Migration `0244` window**: kafka tables/MVs are dropped and recreated
    mid-migration. Brief gap during which events queue in Kafka and aren't consumed.
    Run during a low-traffic window — documented but easy to miss.

### Worth verifying against the spec text

- **5-column floor for compaction.** The RFC said "5 dense columns" — the
  implementation actually packs into the smallest range that satisfies per-team
  uniqueness, with 5 as a floor (a single team holding 5 slots needs 5 distinct
  columns). Likely intentional but worth confirming the spec's wording allows
  this.
- **Reclaim only "this run", not "this workflow"** — relies on the slot table
  storing the per-execution `run_id` in `backfill_temporal_run_id`, which is
  stable across activity retries within one execution but unique across
  scheduled firings.
- **Compaction trigger threshold of 5** assumes a worst-case weekly demand of 5
  new columns. If MAX_SLOTS_PER_TEAM × signups-per-week ever exceeds this, the
  pool can be exhausted mid-cycle.

---

## 10. Tests

Where to look for behavior:

- `posthog/api/test/test_materialized_column_slot.py` — API endpoints, lifecycle.
- `posthog/api/test/test_materialized_column_activity_logging.py` — every state
  transition emits the expected ActivityLog row.
- `posthog/temporal/tests/backfill_materialized_property/test_batched_activities.py`
  — `_plan_column_assignments`, `_build_batched_update_command` (parameterized
  property names — SQL injection guard), `assign_pending_slots` (reclaim same-run,
  ignore other-run), compaction trigger + finalize swap.
- `test_batched_workflow.py` — workflow happy path + rollback under
  Temporal time-skipping.
- `test_coercion_parity.py` — runs real CH mutations against the fixture.
- `nodejs/src/worker/ingestion/create-event.dmat.test.ts` — TS-side coercion
  parity, dual-write during compaction.
- `nodejs/src/utils/materialized-column-slot-manager.test.ts` — kill-switch + team
  isolation.
- `nodejs/src/utils/dmat-kill-switch.test.ts` — fail-open default + Redis flip.
- `posthog/hogql/transforms/test/test_property_types_dmat.py` — dmat-vs-JSON
  read-path parity for every property type.
