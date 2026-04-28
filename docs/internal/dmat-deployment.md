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
hogli django migrate posthog 1126_materializedcolumnslot_pending_and_expand_index
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
hogli django migrate_clickhouse --plan         # confirm 0244 will run
hogli django migrate_clickhouse                 # apply
```

Migration `0244_add_dmat_string_columns_10_99` does this in order:

1. **Drop** `events_json_mv` (MSK) and `events_json_ws_mv` (cloud-only WS).
2. **Drop** `kafka_events_json` and `kafka_events_json_ws`.
3. **ALTER** `sharded_events`, `events`, and (cloud-only) `writable_events` to add
   `dmat_string_10..99`.
4. **CREATE** the kafka tables and MVs from the updated schema.

There is a brief gap between steps 1 and 4 where new events will not flow into
`writable_events`. They land in Kafka, are not consumed during the gap, and are picked
up once the recreated MV resumes. Plan to run the migration during a low-traffic
window.

### 3. Register the weekly Temporal cron schedule

The schedule definition lives in
`posthog/temporal/backfill_materialized_property/schedule.py` but is **not** auto-wired
into worker startup. Run this from a Django shell on a host that can reach Temporal:

```python
import asyncio
from posthog.temporal.backfill_materialized_property.schedule import (
    create_or_update_weekly_dmat_backfill_schedule,
)
from posthog.temporal.common.client import async_connect

async def main():
    client = await async_connect()
    await create_or_update_weekly_dmat_backfill_schedule(client)

asyncio.run(main())
```

The schedule fires every Sunday at 00:00 UTC and uses `ScheduleOverlapPolicy.SKIP` so a
long-running mutation never gets a duplicate firing alongside it.

### 4. Verify the worker has the new workflow registered

The worker needs to know about both `BackfillMaterializedPropertyWorkflow` (legacy, kept
for in-flight runs) and `BackfillMaterializedPropertiesBatchWorkflow` (new). Both are
registered in `posthog/temporal/product_analytics/__init__.py:WORKFLOWS`. Restart the
analytics-platform Temporal worker so it picks up the new workflow definition.

### 5. Smoke test on staging

Before turning this on for production teams:

- Add 1–2 PENDING slots for a low-volume staging team via the staff UI.
- Trigger the workflow manually (don't wait a week):

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

### 6. Roll out to production teams

Phase 1 (RFC): manual assignment for high-value teams. Engineering identifies the
candidates (e.g. via query log analysis) and posts the slot through the staff UI.

## Alerts

Two non-exception bad states emit `posthoganalytics.capture_exception(...)` from the
weekly workflow's activities — Sentry's normal dedup + PagerDuty rules carry them to
oncall. Workflow / activity _failures_ are auto-captured by the Temporal interceptor in
`posthog/temporal/common/posthog_client.py`, so this list only covers states the
workflow recovers from on its own but that still need operator attention.

| Alert message                                                            | Trigger                                                                                                    | Operator response                                                                                                                                                                |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dmat: stranded BACKFILL slots require operator action`                  | A weekly run finds slots in BACKFILL whose `backfill_temporal_workflow_id` is from a prior, dead run.      | Reset the slot(s) back to PENDING via the staff API so the next weekly cycle picks them up. Slots stay harmless (HogQL falls back to JSON for state != READY) but waste columns. |
| `dmat: compaction planner skipped slots — column pool may be exhausting` | The compaction planner couldn't fit one or more slots into a fresh column (per-team uniqueness collision). | One firing is fine — the next weekly run retries. Sustained firings mean compaction is stalling and the column pool is draining; investigate `MAX_SLOTS_PER_TEAM` / cycle.       |

Workflow duration / mutation latency are covered by Temporal's built-in
`temporal_activity_execution_latency_seconds{activity_name="run_batched_mutation"}` —
no custom histogram needed.

The on-call's pre-firing check ("no other large mutation queued on `sharded_events`")
should be on the same Grafana dashboard — query `system.mutations WHERE table='sharded_events'
AND is_done=0` and compare against the cron firing time.

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

### Crash-recovery between mutation completion and finalize

The workflow does:

```text
assign → wait → mutation → activate(PENDING→READY) → finalize_compaction(swap)
```

If the worker crashes between the mutation finishing on ClickHouse and the
`finalize_compaction` activity running, slots stay in their pre-swap state with
`compaction_target_slot_index` still set. Plugin-server keeps dual-writing to both
columns (correct), HogQL keeps reading the old column (correct), but no automatic
recovery happens. The next weekly run won't re-trigger compaction for those slots
because the `compaction_target_slot_index` filter excludes them.

**Recovery:** an operator runs `finalize_compaction` manually for the stuck slot IDs,
or transitions them back to "no target" via the Django shell to free the columns.

**Long-term fix:** the next workflow run should detect "BACKFILL slots / compacting
slots from a stale workflow_id" and either re-finalize or roll back.

### Mutation queue coordination

A long-running dmat mutation on `sharded_events` blocks every other mutation on the
table — most notably person-ID squashing and session-on-events squashing. Running
weekly is the only mitigation in this branch. The RFC mentions folding dmat updates
into the person-ID squashing mutation as future work; not done.

**Mitigation today:** the on-call should confirm no other large mutation is queued on
`sharded_events` before the weekly cron fires (Sunday 00:00 UTC).

### Mutation-too-large is detected, but a single oversized column isn't split

`run_batched_mutation` chunks assignments at column boundaries when the total branch
count exceeds `MAX_MULTIIF_BRANCHES_PER_MUTATION = 500`. A single column with more
branches than the cap is submitted as its own chunk — we never split a `multiIf`
across mutations because each `multiIf` is self-contained per column. This is fine
today (max teams per column ≤ team count, which is far under 500) but if a single
column ever crosses the cap it will probably hit `max_query_size` and the activity
will fail loudly via the warning log line plus the mutation submission error.

### Real ClickHouse integration test for the batched mutation is missing

All Python tests for the new workflow mock `get_cluster()` and
`AlterTableMutationRunner`. The legacy per-slot activity has integration tests against
a real ClickHouse, but the batched `multiIf` mutation has not been exercised against
a real cluster. The plan is to validate it on staging during step 5 above.

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
`backfill_materialized_column` mutation polls `system.mutations` every 15s with a
12-hour activity timeout, so multi-hour mutations are tolerated, but at the
production-scale 25B-row teams this is untested. Use Temporal's built-in
`temporal_activity_execution_latency_seconds{activity_name="run_batched_mutation"}`
to measure this once the first real run goes through; until then, the staging smoke
test is the only data point.

### Compaction is best-effort

If the per-team uniqueness invariant means a slot can't be packed into the new dense
range, the planner skips it and logs a warning. The next weekly run picks it up after
some columns are freed. Worst case: the global `free_count < 5` check stays true for
multiple cycles until enough capacity opens up. Not a correctness issue, just possibly
slow to converge — `dmat_compaction_skipped_slots_total` is the metric to watch.
