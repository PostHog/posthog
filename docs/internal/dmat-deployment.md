# Dynamic property materialization (dmat) — deployment & known gaps

The dmat system materializes per-team event properties into dedicated `dmat_string_*`
ClickHouse columns so HogQL can avoid scanning the JSON `properties` blob. The design is
in the dmat RFC; this file is the operator's checklist for turning it on, plus the
honest list of gaps the launch hasn't filled.

## Deployment ordering

Migrations land first, then plugin-server. The new slot manager doesn't exist on master,
so deploying plugin-server before the Postgres migration would have it select against a
column that doesn't exist yet. The slot table is empty in production today, so the
`RemoveField` of `property_type` is safe even though it's normally a multi-phase
operation per [safe-django-migrations](../published/handbook/engineering/safe-django-migrations.md).

1. Apply the Postgres migration.
2. Apply the ClickHouse migration.
3. Roll out new Django code.
4. Roll out new plugin-server.

If 3 and 4 swap, plugin-server logs slot-cache load errors until the migration finishes.

## Deployment steps

### 1. Apply Django migrations

```sh
hogli django migrate posthog 1144_materializedcolumnslot_pending_and_expand_index
```

Adds the `PENDING` state, makes `slot_index` nullable, expands the index range to
`0..99`, adds `compaction_target_slot_index`, drops `property_type`. Detail in the
migration's header comment.

### 2. Apply the ClickHouse migration

```sh
hogli django migrate_clickhouse --plan         # confirm 0249 will run
hogli django migrate_clickhouse                # apply
```

Migration `0249_add_dmat_string_columns_10_99` does this in order:

1. Drop `events_json_mv` (MSK) and `events_json_ws_mv` (cloud-only WS).
2. Drop `kafka_events_json` and `kafka_events_json_ws`.
3. Drop the legacy typed columns (`dmat_numeric_*`, `dmat_bool_*`, `dmat_datetime_*`)
   added by migration 0179. They were never wired into the kafka tables / MV, so no
   production row stored a value in them.
4. Add `dmat_string_10..99` to `sharded_events`, `events`, and (cloud-only)
   `writable_events`.
5. Recreate the kafka tables and MVs.
6. Create `dmat_slot_assignments` (table) and `dmat_slot_assignments_dict` (dictionary)
   ON CLUSTER. The weekly mutation reads `(team_id, column_index) → property_name` from
   the dict so the SQL stays constant-size regardless of adoption. Empty until the first
   workflow run; an empty dict makes `dictHas` return 0 and the SET expression falls
   through to the no-op fallback.

There is a brief gap between steps 1 and 5 where new events don't flow into
`writable_events` — they queue in Kafka and resume once the recreated MV catches up.
Run during a low-traffic window.

### 3. Register the weekly Temporal cron schedules

Two schedules — compaction (Saturday 00:00 UTC) and PENDING allocation (Sunday 00:00 UTC).
The 24h gap lets a long compaction mutation finish (and free its old columns) before
allocation reads the free pool. Both are defined in
`posthog/temporal/backfill_materialized_property/schedule.py` but **not** auto-wired.
Run from a Django shell:

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

Both use `ScheduleOverlapPolicy.SKIP` so a long-running mutation never gets a duplicate
firing alongside it. Compaction self-skips when free-column count is at or above
`COMPACTION_FREE_COLUMN_THRESHOLD` (10), so most weeks are no-ops.

### 4. Verify the worker has the new workflows registered

`BackfillMaterializedPropertiesBatchWorkflow` and `CompactMaterializedColumnsWorkflow`
are registered in `posthog/temporal/product_analytics/__init__.py:WORKFLOWS`. Restart
the analytics-platform Temporal worker so it picks up the new definitions.

### 5. Smoke test on staging

- Add 1–2 PENDING slots for a low-volume staging team via the staff UI.
- Trigger the PENDING-allocation workflow manually:

  ```python
  await client.execute_workflow(
      "backfill-materialized-properties-batch",
      BackfillMaterializedPropertiesBatchInputs(cache_refresh_wait_seconds=180),
      id="dmat-staging-smoke-1",
      task_queue=settings.TEMPORAL_TASK_QUEUE,
  )
  ```

  Confirm the slot transitions PENDING → BACKFILL → READY, that `dmat_string_<n>` is
  populated for new and historical events, and that HogQL queries on the property hit
  the column.

- For compaction, hand-set `compaction_target_slot_index` on a small READY staging slot
  to a free column index, then trigger:

  ```python
  await client.execute_workflow(
      "compact-materialized-columns",
      CompactMaterializedColumnsInputs(cache_refresh_wait_seconds=180),
      id="dmat-compact-staging-smoke-1",
      task_queue=settings.TEMPORAL_TASK_QUEUE,
  )
  ```

  The workflow treats the hand-set target as in-flight, runs the mutation, and finalizes
  the swap. Verify `slot_index` ends up at the new column.

### 6. Roll out to production teams

Phase 1 (RFC): manual assignment for high-value teams via the staff UI.

## Alerts

The weekly workflows emit `posthoganalytics.capture_exception(...)` for non-exception
bad states they recover from on their own but that still need operator attention.
Workflow / activity _failures_ are auto-captured by the Temporal interceptor in
`posthog/temporal/common/posthog_client.py`.

| Alert message                                                                                    | Trigger                                                                                     | Operator response                                                                                                                          |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `dmat: stranded BACKFILL slots require operator action`                                          | Slots in BACKFILL whose `backfill_temporal_run_id` is from a prior, dead run.               | Reset to PENDING via the staff API. Slots are harmless (HogQL falls back to JSON for state != READY) but waste columns.                    |
| `dmat: compaction planner skipped slots — column pool may be exhausting`                         | Per-team uniqueness collision prevented packing one or more slots into a fresh column.      | One firing is fine — next week retries. Sustained firings mean the column pool is draining; investigate `MAX_SLOTS_PER_TEAM` / cycle.      |
| `dmat: PENDING allocation refused — free column pool below threshold; compaction must run first` | `free_count < COMPACTION_FREE_COLUMN_THRESHOLD` — allocation skipped to protect compaction. | Check the last compaction run in Temporal. PENDING slots stay PENDING and resume automatically once compaction succeeds and frees columns. |

Workflow / mutation duration is covered by Temporal's
`temporal_activity_execution_latency_seconds{activity_name="run_batched_mutation"}`.

The on-call's pre-firing check ("no other large mutation queued on `sharded_events`")
should sit on the same Grafana dashboard — query `system.mutations WHERE
table='sharded_events' AND is_done=0` against both cron firing times.

## Emergency kill switch (plugin-server ingestion)

If a bug is detected in the dmat ingestion path (wrong values, divergence from JSON,
plugin-server panicking), oncall can stop _all_ dmat-column writes globally without a
redeploy:

```sh
redis-cli set dmat_kill_switch 1     # disable; takes effect within ~60s
redis-cli del dmat_kill_switch       # re-enable
```

Every plugin-server process polls this key (`nodejs/src/utils/dmat-kill-switch.ts`) on a
60s background refresher. When set, `MaterializedColumnSlotManager.getSlots()` short-
circuits to `[]` for every team → `extractDynamicMaterializedColumns` writes nothing →
`dmat_string_*` columns stop receiving new data. Existing column data is unchanged;
HogQL keeps reading whatever's there (no read-side disruption).

For a single-slot bad-data incident (one team's column has wrong values), prefer the
per-slot fix: `DELETE` the slot via the staff API. HogQL falls back to JSON for that
property, ingestion stops dual-writing on the next cache refresh, and the column is
freed for the next workflow run.

## Known gaps & cut corners

### Mutation queue coordination

A long-running dmat mutation on `sharded_events` blocks every other mutation on the
table — most notably person-ID squashing and session-on-events squashing. Running
weekly is the only mitigation in this branch. The RFC mentions folding dmat updates into
person-ID squashing as future work; not done.

The two-workflow design also means a compaction week submits **two** mutations across
the weekend (Saturday + Sunday). This roughly doubles cluster write load for the ~2
weeks per year compaction actually fires, in exchange for a planner so trivially correct
that nothing competes for the same free pool inside one transaction.

**Mitigation:** on-call should confirm no other large mutation is queued on
`sharded_events` before either weekly cron fires.

### Real ClickHouse integration test for the batched mutation is missing

Dispatch + extraction parity is exercised end-to-end via
`test_coercion_parity.py::TestDictBackedDispatchCoercion`,
`test_dmat_dictionary.py` (dict round-trip), and
`test_cluster.py::test_cycle_marker_survives_format_query` (cross-cycle dedup). The full
`run_batched_mutation` activity itself is mocked in workflow tests — staging validation
in step 5 is what proves the wire-level shape on a multi-shard cluster.

### Frontend kea-typegen file is not regenerated

`materializedColumnsLogic.ts` references `materializedColumnsLogicType` which kea
generates at build time. The repo doesn't check that file in. Type errors against this
file already existed before this branch.

### Mutation duration hasn't been measured

The RFC's open question of how long a real backfill takes is still open. The
`run_batched_mutation` activity polls `system.mutations` every 15s with a 12-hour
activity timeout, so multi-hour mutations are tolerated, but at the production-scale
25B-row teams this is untested. Use Temporal's
`temporal_activity_execution_latency_seconds{activity_name="run_batched_mutation"}`
once the first real run goes through.

### Compaction is best-effort

If per-team uniqueness prevents packing a slot into the new dense range, the planner
skips it and the workflow fires `dmat: compaction planner skipped slots — column pool
may be exhausting`. The next weekly run picks it up after columns free up. Worst case:
the global threshold check stays true for multiple cycles until enough capacity opens
up — slow convergence, not a correctness issue.

## Things to verify before shipping

Items specific to the dict-backed mutation. Each one is small but worth a sanity check
the first time the workflow runs against a real cluster.

- **Dictionary cardinality.** `dmat_slot_assignments_dict` uses
  `LAYOUT(COMPLEX_KEY_HASHED())` (RAM-resident). Each row ≈ 100 bytes, so 100k pairs is
  ~10 MB per replica — invisible. Revisit if adoption ever crosses ~5M entries
  (≈ 500 MB), at which point `SSD_CACHE` would bound memory.
- **Per-host populate semantics.** A populate failure on any host raises an
  `ExceptionGroup` from `cluster.map_all_hosts(...)`, and the reload step never runs —
  the mutation can't see a half-populated cluster. Temporal retries the activity;
  TRUNCATE+INSERT is end-state idempotent. If you see populates retrying repeatedly,
  the failure is on the CH side, not in activity logic.
- **IN-list pruning.** The WHERE
  `team_id IN (SELECT DISTINCT team_id FROM dmat_slot_assignments)` lets the merge-tree
  engine skip parts that contain none of the selected teams. Overlapping parts are
  rewritten with the SET applied only to matching rows. If the dict-source table is
  empty, the IN-list is empty and the mutation is a complete no-op.
- **ON CLUSTER DDL covers fresh replicas.** A replica added after the migration inherits
  both the table and the dictionary via `system.distributed_ddl_queue`. The first
  `populate_slot_assignments` after the new replica joins writes its local copy and
  reloads its local dict.
