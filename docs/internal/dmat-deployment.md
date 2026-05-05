# Dynamic property materialization (dmat) — deployment & known gaps

The dmat system materializes per-team event properties into dedicated `dmat_string_*`
ClickHouse columns so HogQL can avoid scanning the JSON `properties` blob. The design
is documented in the dmat RFC; this file is the operator's checklist for turning it on
and the honest list of gaps the launch hasn't filled in yet.

## Deployment ordering

Two independent deploy pipelines are involved — Django (which runs both Postgres and
ClickHouse migrations) and plugin-server (`nodejs/`). They cannot be coordinated to
deploy in lock-step. The schema and code on this branch are designed so that **migrations
land first, then plugin-server**:

1. Apply the Postgres migration (step 1 below). The change is additive plus a single
   `RemoveField` on a column that no production code path actually reads — see step 1.
2. Apply the ClickHouse migration (step 2 below). It adds new `dmat_string_*` columns
   and recreates the kafka tables / MVs. Until plugin-server starts dual-writing, the
   new columns just stay NULL.
3. Roll out the new Django code. Old Django pods stop reading `slot.property_type`
   (the column is already gone, but no read path exercises it on production data).
4. Only **after** the migrations have applied, deploy the new plugin-server. The slot
   manager (`nodejs/src/utils/materialized-column-slot-manager.ts`) is brand-new on
   this branch — the version on master doesn't touch the slot table — so there is no
   "old plugin-server reading new schema" hazard. The hazard runs the other way:
   deploying the new plugin-server before the Postgres migration would let it issue
   selects against columns that don't exist yet.

If steps 3 and 4 happen out of order, plugin-server will log slot-cache load errors
until either the migration finishes or plugin-server is restarted.

## Deployment steps

The order matters because the kafka tables / MVs are recreated mid-migration.

### 1. Apply Django migrations

```sh
hogli django migrate posthog 1144_materializedcolumnslot_pending_and_expand_index
```

This applies the single in-flight migration that brings the slot table fully in line with
the dmat RFC:

- adds the `PENDING` state and makes it the default,
- makes `slot_index` nullable (PENDING slots have no column yet) and expands the valid
  index range to 0..99,
- adds the `compaction_target_slot_index` field for the dual-write swap during compaction,
- drops `property_type` and the constraints / index that were keyed on it (per the RFC,
  every dmat column is `Nullable(String)` — HogQL applies the type wrapper at read time).

The slot table is empty in production today, so the `RemoveField` is safe even though it
is normally a multi-phase operation per
[safe-django-migrations](../published/handbook/engineering/safe-django-migrations.md).

### 2. Apply the ClickHouse migration

```sh
hogli django migrate_clickhouse --plan         # confirm 0249 will run
hogli django migrate_clickhouse                 # apply
```

Migration `0249_add_dmat_string_columns_10_99` does this in order:

1. **Drop** `events_json_mv` (MSK) and `events_json_ws_mv` (cloud-only WS).
2. **Drop** `kafka_events_json` and `kafka_events_json_ws`.
3. **ALTER** `sharded_events`, `events`, and (cloud-only) `writable_events` to add
   `dmat_string_10..99`.
4. **CREATE** the kafka tables and MVs from the updated schema.
5. **CREATE** `dmat_slot_assignments` (table) and `dmat_slot_assignments_dict`
   (dictionary) ON CLUSTER. The weekly backfill workflow writes this table on every host
   and reloads the dictionary before submitting its mutation; the mutation reads the
   `(team_id, column_index) → property_name` mapping out of the dictionary so the SQL
   stays a constant size regardless of how many teams have adopted dmat. Empty until the
   first workflow run populates it; an empty dict makes `dictHas` return 0 and the
   mutation's SET expression falls through to the no-op fallback.

There is a brief gap between steps 1 and 4 where new events will not flow into
`writable_events`. They land in Kafka, are not consumed during the gap, and are picked
up once the recreated MV resumes. Plan to run the migration during a low-traffic
window.

### 3. Register the weekly Temporal cron schedules

Two independent schedules need to exist — one for compaction and one for PENDING
allocation. They run on different days of the week so a long compaction mutation has time
to finish (and free its old columns) before the allocation workflow looks at the free
pool. Both definitions live in
`posthog/temporal/backfill_materialized_property/schedule.py` but are **not** auto-wired
into worker startup. Run this from a Django shell on a host that can reach Temporal:

```python
import asyncio
from posthog.temporal.backfill_materialized_property.schedule import (
    create_or_update_weekly_dmat_backfill_schedule,
    create_or_update_weekly_dmat_compact_schedule,
)
from posthog.temporal.common.client import async_connect

async def main():
    client = await async_connect()
    await create_or_update_weekly_dmat_compact_schedule(client)
    await create_or_update_weekly_dmat_backfill_schedule(client)

asyncio.run(main())
```

- `weekly-dmat-compact` fires Saturday 00:00 UTC. Self-skips when the global free-column
  count is at or above `COMPACTION_FREE_COLUMN_THRESHOLD` (10), so most weeks are no-ops.
- `weekly-dmat-backfill` fires Sunday 00:00 UTC. Allocates columns for any PENDING slots
  and runs the historical backfill mutation.

Both schedules use `ScheduleOverlapPolicy.SKIP` so a long-running mutation never gets a
duplicate firing alongside it. The 24h gap between Saturday and Sunday firings is the
buffer that lets compaction's mutation finish before allocation reads the free pool.

### 4. Verify the worker has the new workflows registered

The worker needs to know about two workflows:

- `BackfillMaterializedPropertiesBatchWorkflow` — weekly PENDING allocation.
- `CompactMaterializedColumnsWorkflow` — weekly compaction (self-skips most weeks).

Both are registered in `posthog/temporal/product_analytics/__init__.py:WORKFLOWS`.
Restart the analytics-platform Temporal worker so it picks up the new workflow
definition.

### 5. Smoke test on staging

Before turning this on for production teams:

- Add 1–2 PENDING slots for a low-volume staging team via the staff UI.
- Trigger the PENDING-allocation workflow manually (don't wait a week):

  ```python
  await client.execute_workflow(
      "backfill-materialized-properties-batch",
      BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=180),
      id="dmat-staging-smoke-1",
      task_queue=settings.TEMPORAL_TASK_QUEUE,
  )
  ```

- Confirm the slot transitions PENDING → BACKFILL → READY, that
  `dmat_string_<n>` is populated for new and historical events, and that HogQL queries
  on the property hit the column (check `EXPLAIN` or the query log).
- To smoke-test compaction without driving the column pool to the threshold, manually
  set `compaction_target_slot_index` on a small READY staging slot to a free column
  index, then trigger:

  ```python
  await client.execute_workflow(
      "compact-materialized-columns",
      CompactMaterializedColumnsInputs(cache_refresh_wait_seconds=180),
      id="dmat-compact-staging-smoke-1",
      task_queue=settings.TEMPORAL_TASK_QUEUE,
  )
  ```

  The workflow will treat the hand-set target as in-flight, run the mutation, and
  finalize the swap. Verify the slot's `slot_index` ends up at the new column and the
  old `dmat_string_<n>` is no longer being read by HogQL.

### 6. Roll out to production teams

Phase 1 (RFC): manual assignment for high-value teams. Engineering identifies the
candidates (e.g. via query log analysis) and posts the slot through the staff UI.

## Alerts

Two non-exception bad states emit `posthoganalytics.capture_exception(...)` from the
weekly workflows' activities — Sentry's normal dedup + PagerDuty rules carry them to
oncall. Workflow / activity _failures_ are auto-captured by the Temporal interceptor in
`posthog/temporal/common/posthog_client.py`, so this list only covers states the
workflows recover from on their own but that still need operator attention.

| Alert message                                                                                    | Trigger                                                                                                                                 | Operator response                                                                                                                                                                                                                                                                |
| ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dmat: stranded BACKFILL slots require operator action`                                          | A weekly run finds slots in BACKFILL whose `backfill_temporal_workflow_id` is from a prior, dead run.                                   | Reset the slot(s) back to PENDING via the staff API so the next weekly cycle picks them up. Slots stay harmless (HogQL falls back to JSON for state != READY) but waste columns.                                                                                                 |
| `dmat: compaction planner skipped slots — column pool may be exhausting`                         | The compaction planner couldn't fit one or more slots into a fresh column (per-team uniqueness collision).                              | One firing is fine — the next weekly run retries. Sustained firings mean compaction is stalling and the column pool is draining; investigate `MAX_SLOTS_PER_TEAM` / cycle.                                                                                                       |
| `dmat: PENDING allocation refused — free column pool below threshold; compaction must run first` | The PENDING-allocation workflow saw `free_count < COMPACTION_FREE_COLUMN_THRESHOLD` and skipped fresh allocation to protect compaction. | Compaction either failed last firing or is still running. Check the compaction workflow's last run in Temporal — if it failed, investigate the underlying mutation error. PENDING slots stay PENDING and get picked up automatically once compaction succeeds and frees columns. |

Workflow duration / mutation latency are covered by Temporal's built-in
`temporal_activity_execution_latency_seconds{activity_name="run_batched_mutation"}` —
no custom histogram needed.

The on-call's pre-firing check ("no other large mutation queued on `sharded_events`")
should be on the same Grafana dashboard — query `system.mutations WHERE table='sharded_events'
AND is_done=0` and compare against both cron firing times (Saturday 00:00 UTC for
compaction, Sunday 00:00 UTC for PENDING allocation).

## Emergency kill switch (plugin-server ingestion)

If a bug is detected in the dmat ingestion path (wrong values written to columns,
divergence from JSON, plugin-server panicking, etc.), oncall can stop _all_ dmat-column
writes globally without a redeploy:

```sh
redis-cli set dmat_kill_switch 1     # disable; takes effect within ~60s
redis-cli del dmat_kill_switch       # re-enable
```

Mechanism: every plugin-server process polls this Redis key (via
`nodejs/src/utils/dmat-kill-switch.ts`) on a 60-second background refresher and gates
the slot-manager cache on it. When set, `MaterializedColumnSlotManager.getSlots()` short-
circuits to `[]` for every team → `extractDynamicMaterializedColumns` writes nothing →
`dmat_string_*` columns stop receiving new data. Existing data in the columns is
unchanged; HogQL keeps reading whatever is already there (graceful — no read-side
disruption while you investigate).

To verify it took effect, check the slot manager's debug log on any worker after ~60s
or send a test event and confirm `dmat_string_<idx>` is NULL on the new row.

For a single-slot bad-data incident (one team's column has wrong values), prefer the
per-slot fix instead of the global kill: `DELETE` the slot via the staff API. HogQL
falls back to JSON for that property, ingestion stops dual-writing on the next cache
refresh, and the column is freed for the next workflow run.

## Known gaps & cut corners

These are the things this branch deliberately does not solve. Tracking them here so
they don't get forgotten.

### Mutation queue coordination

A long-running dmat mutation on `sharded_events` blocks every other mutation on the
table — most notably person-ID squashing and session-on-events squashing. Running
weekly is the only mitigation in this branch. The RFC mentions folding dmat updates
into the person-ID squashing mutation as future work; not done.

The two-workflow design also means a compaction week submits **two** mutations across
the weekend: the compaction firing on Saturday and the PENDING-allocation firing on
Sunday. Both are large writes against `sharded_events`. This is the cost of the naive
split — we accept a roughly doubled cluster write load for the ~2 weeks per year
compaction actually fires, in exchange for the planner staying so trivially correct
that nothing competes for the same free pool inside a single transaction.

**Mitigation today:** on-call should confirm no other large mutation is queued on
`sharded_events` before either weekly cron fires (Saturday 00:00 UTC for compaction,
Sunday 00:00 UTC for PENDING allocation).

### Mutation SQL is constant-size via dict-backed dispatch

`run_batched_mutation` no longer encodes per-team `multiIf` branches in the SQL. Each
affected `dmat_string_<idx>` column gets a single
`if(dictHas('dmat_slot_assignments_dict', (team_id, idx)), <extract>, dmat_string_<idx>)`
SET clause; the team and property mapping lives in the dictionary at runtime. The WHERE
uses `team_id IN (SELECT DISTINCT team_id FROM dmat_slot_assignments)` for primary-key
part pruning on `sharded_events`. SQL stays a few KB regardless of team count.

The dict is populated by the `populate_slot_assignments` activity which runs in both
the PENDING and compaction workflows between the assign step and the cache-refresh
sleep. The activity calls `cluster.map_all_hosts(...)` twice — first to TRUNCATE+INSERT
the per-host local table, then to `SYSTEM RELOAD DICTIONARY` on every host. A failure
on any host raises before the reload step runs, so the mutation never sees a half-
populated cluster. Retry is end-state idempotent.

The mutation also embeds a 32-bit hash of `workflow_run_id` as a no-op
`AND <int> = <int>` in WHERE so `AlterTableMutationRunner.find_existing_mutations`
distinguishes cycles. Without it, the dict-based SQL would be byte-identical across
cycles and a fresh cycle would falsely reattach to the prior cycle's completed
mutation.

### Real ClickHouse integration test for the batched mutation is missing

The dict-backed SQL is exercised end-to-end on a real ClickHouse via
`posthog/temporal/tests/backfill_materialized_property/test_coercion_parity.py::TestDictBackedDispatchCoercion`
(dispatch + extraction parity for every fixture case),
`posthog/clickhouse/test/test_dmat_dictionary.py` (dict round-trip), and
`posthog/clickhouse/test/test_cluster.py::test_cycle_marker_survives_format_query`
(cross-cycle dedup). The full `run_batched_mutation` activity itself is still mocked in
the workflow tests; staging validation in step 5 is what proves the wire-level shape
on a multi-shard cluster.

### Frontend kea-typegen file is not regenerated

`materializedColumnsLogic.ts` references `materializedColumnsLogicType` which kea
generates at build time. The repo doesn't check that file in. Type errors against
this file already existed before this branch.

### Legacy typed columns are dropped, not left in place

`dmat_numeric_*`, `dmat_bool_*`, `dmat_datetime_*` are removed in this branch. They
were added by master migration 0179 to `sharded_events` / `events` only and were never
wired into the kafka tables / MV / writable*events, so no production row ever stored a
value in them. The 0244 ClickHouse migration drops them as part of its kafka recreate.
Per the RFC, dmat is string-only; HogQL applies the per-property-type wrapper at read
time exactly the way it does for normal `mat*\*` columns.

### Mutation duration hasn't been measured

The RFC's open question about how long a real backfill takes is still open. The
`run_batched_mutation` activity polls `system.mutations` every 15s with a
12-hour activity timeout, so multi-hour mutations are tolerated, but at the
production-scale 25B-row teams this is untested. Use Temporal's built-in
`temporal_activity_execution_latency_seconds{activity_name="run_batched_mutation"}`
to measure this once the first real run goes through; until then, the staging smoke
test is the only data point.

### Compaction is best-effort

If the per-team uniqueness invariant means a slot can't be packed into the new dense
range, the planner skips it and logs a warning. The next weekly run picks it up after
some columns are freed. Worst case: the global `free_count < COMPACTION_FREE_COLUMN_THRESHOLD`
check stays true for multiple cycles until enough capacity opens up. Not a correctness
issue, just possibly slow to converge — `dmat_compaction_skipped_slots_total` is the
metric to watch.

## Things to verify before shipping

Items specific to the dict-backed mutation. Each one is small but worth a sanity check
the first time the workflow runs against a real cluster.

- **Dictionary cardinality at adoption rate.** `dmat_slot_assignments_dict` uses
  `LAYOUT(COMPLEX_KEY_HASHED())`, which holds entries in RAM. Each row is roughly 100
  bytes (UInt64 + UInt8 + small property name string). At 100k `(team, column_index)`
  pairs that's about 10 MB per replica — invisible. Only worth revisiting if dmat
  adoption ever crosses ~5M entries (≈ 500 MB), at which point switching to
  `SSD_CACHE` would bound memory use.
- **Cycle marker collision is irrelevant.** The marker is a 32-bit hash of
  `workflow_run_id`. Collision rate per cycle is ~1/2³² — never going to fire.
- **Per-host populate semantics.** A populate failure on any host raises an
  `ExceptionGroup` from `cluster.map_all_hosts(...)`, the activity fails, and the
  mutation never runs against a half-populated state. Temporal retries the activity;
  TRUNCATE+INSERT is end-state idempotent so the retry converges. If you see a
  populate retrying repeatedly, look at the failing host first — the failure is on the
  CH side, not in the activity logic.
- **Mutation rewrites parts that overlap the IN-list.** The WHERE
  `team_id IN (SELECT DISTINCT team_id FROM dmat_slot_assignments)` lets the merge-tree
  engine skip parts that contain none of the selected teams. Parts that overlap are
  rewritten, with the SET applied only to matching rows — this is normal mutation
  behavior, not a regression. If the dict-source table is empty, the IN-list is empty
  and the mutation is a complete no-op.
- **ON CLUSTER DDL covers fresh replicas.** The migration creates the table and
  dictionary `ON CLUSTER`, so a replica added to the cluster after the migration
  inherits both via the standard `system.distributed_ddl_queue` path. The first
  `populate_slot_assignments` after the new replica joins will write to its local
  copy and reload its local dict, so it ends up consistent with the rest of the
  cluster on the next workflow firing.
