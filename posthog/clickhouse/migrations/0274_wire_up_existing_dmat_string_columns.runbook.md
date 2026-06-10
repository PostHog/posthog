# Manual migration runbook: dmat_string wiring on cloud (migration 0274)

Migration `0274_wire_up_existing_dmat_string_columns` is a **no-op on cloud** (US/EU/DEV).
This runbook is the manual equivalent, to be executed by (or under the supervision of) the
ClickHouse team, one region at a time. It exists because two automated attempts (0256, 0267) failed against the real cluster topologies — 0267 caused the 2026-06-01 ingestion incident — and the agreed
process is now: events-pipeline schema changes on cloud are applied by hand, and the repo
records them afterwards.

Goal state per region, all of it additive:

1. `dmat_string_0..9 Nullable(String)` exist on `sharded_events`, `events`, and
   `writable_events`.
2. The live kafka table / MV pair (`kafka_events_json_ws` / `events_json_ws_mv` on the
   ingestion layer) projects `dmat_string_0..9` from the topic into `writable_events`.
3. `dmat_slot_assignments` (plain ReplacingMergeTree) and `dmat_slot_assignments_dict`
   exist on every **data** node of the main cluster.

Explicitly **out of scope** (do not bundle with this work):

- Dropping the never-wired typed columns (`dmat_numeric_*`, `dmat_bool_*`,
  `dmat_datetime_*`). DROP COLUMN mutations stuck on pre-`inserted_at` parts during
  the 2026-06-01 incident and had to be killed. Cleanup is a separate ClickHouse-team task
  (per-partition drops after the old parts are repaired).
- Repairing old parts that physically lack `inserted_at` (seen on EU, partitions
  ~2020–2023). Tracked separately; §6 covers how this interacts with the backfill.

Region order: **dev → US → EU.** Dev is the rehearsal (it already received 0267's
changes, so it should verify as already-done). EU goes last: its state is the messiest
(killed mutations left typed columns half-dropped across shards, and `writable_events`
was recreated during the incident without any dmat columns).

Rules that this runbook inherits from the 2026-06-01 incident:

- **Never** drop/recreate the WS kafka table or MV from repo SQL. The live definitions
  carry environment-specific `mat_*` columns that are not in the repo. Always start from
  the live `SHOW CREATE TABLE`.
- **Never** drop/recreate `writable_events` (or any Distributed table) to change its
  schema — dropping a Distributed table silently discards its async-insert queue
  (data loss; happened during the 2026-06-01 incident). `ALTER TABLE ... ADD COLUMN` is metadata-only
  and safe.
- Additive DDL only: `ADD COLUMN IF NOT EXISTS`, `CREATE ... IF NOT EXISTS`. No DROP
  COLUMN, no MATERIALIZE COLUMN.

## 1. Pre-flight (per region)

- [ ] ClickHouse team engineer assigned and executing/supervising; announced in
      `#team-clickhouse` with a link to this runbook.
- [ ] Pick a low-traffic window; do not run while any other mutation or cluster
      maintenance is in flight: `SELECT * FROM clusterAllReplicas('posthog', system.mutations) WHERE NOT is_done`.
- [ ] Confirm the deploy containing migration 0274 has rolled out (the migration no-ops
      on cloud, so order is not load-bearing — but it keeps `migration-sync` green and
      records intent).

## 2. Discovery (read-only)

Capture current state; every later phase is checked against this snapshot.

```sql
-- Column inventory on the main cluster
SELECT hostName() AS host, table,
       countIf(name LIKE 'dmat_string_%')   AS dmat_string_cols,
       countIf(name LIKE 'dmat_numeric_%'
            OR name LIKE 'dmat_bool_%'
            OR name LIKE 'dmat_datetime_%') AS dmat_typed_cols
FROM clusterAllReplicas('posthog', system.columns)
WHERE database = 'posthog' AND table IN ('sharded_events', 'events', 'writable_events')
GROUP BY host, table
ORDER BY table, host;
```

On each **ingestion-layer host** (these are not necessarily reachable via the `posthog`
cluster function — connect directly; the layer is mid-migration EKS→EC2, get the host
list from the ClickHouse team):

```sql
SHOW CREATE TABLE posthog.writable_events;
SHOW CREATE TABLE posthog.kafka_events_json_ws;
SHOW CREATE TABLE posthog.events_json_ws_mv;
SELECT database, table, consumer_id, assignments.topic, is_currently_used
FROM system.kafka_consumers;
```

- [ ] Save every `SHOW CREATE TABLE` output to the `PostHog/clickhouse_schemas` repo
      (during the 2026-06-01 incident there were no schema backups of the ingestion nodes; fix that as
      part of this work).
- [ ] Note which kafka/MV pairs are _actually consuming_ (`system.kafka_consumers`).
      Leftover MSK-era pairs may still exist; only the live pair gets recreated in §4.
- [ ] Expected findings: US `sharded_events` has all 40 dmat columns; EU typed columns
      are partially dropped (mutations were killed on shards 1/3/8) — that asymmetry is
      fine and stays; `writable_events` has no dmat columns anywhere on cloud.

## 3. Additive columns (no ingestion impact, metadata-only)

Order: data tables first, then the write path, so nothing references a column that
doesn't exist downstream of it yet.

```sql
-- 3a. sharded_events — one replica per shard; replication propagates the ALTER.
--     ADD COLUMN is metadata-only: no mutation, no part rewrite, safe even where old
--     parts are broken. No-op where 0179 already added the columns.
ALTER TABLE posthog.sharded_events
    ADD COLUMN IF NOT EXISTS dmat_string_0 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_1 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_2 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_3 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_4 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_5 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_6 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_7 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_8 Nullable(String),
    ADD COLUMN IF NOT EXISTS dmat_string_9 Nullable(String);

-- 3b. events (Distributed read table) — every data node, same ADD COLUMN list.
ALTER TABLE posthog.events
    ADD COLUMN IF NOT EXISTS dmat_string_0 Nullable(String),
    /* ... dmat_string_1..9 as above ... */
    ADD COLUMN IF NOT EXISTS dmat_string_9 Nullable(String);

-- 3c. writable_events — every host where it exists (ingestion layer; plus data nodes
--     in any region where discovery found it there). ALTER, never recreate.
ALTER TABLE posthog.writable_events
    ADD COLUMN IF NOT EXISTS dmat_string_0 Nullable(String),
    /* ... dmat_string_1..9 as above ... */
    ADD COLUMN IF NOT EXISTS dmat_string_9 Nullable(String);
```

- [ ] Verify: rerun the §2 inventory; `dmat_string_cols = 10` for all three tables on
      every host where the table exists.

## 4. Kafka table + MV recreate (the only step with ingestion impact)

The kafka table's column list is fixed at CREATE time, so it must be recreated for the
MV to receive the dmat columns. The MV must be recreated to project them.

1. Build the new DDL **from the §2 live `SHOW CREATE TABLE` output** (re-capture if more
   than a day old):
   - kafka table: live DDL + the 10 `dmat_string_N Nullable(String)` columns appended to
     the column list (before the `SETTINGS`/engine clause).
   - MV: live DDL with `dmat_string_0, ..., dmat_string_9` appended to the SELECT list.
     MV→target inserts match by name, so position is irrelevant; §3c must be done first.
2. - [ ] Diff new-vs-live DDL with a second engineer. The only delta must be the 10
         columns. Anything else means the template went stale — stop.
3. Roll **one ingestion host at a time** (the consumer group rebalances; remaining hosts
   keep consuming):

   ```sql
   DROP TABLE IF EXISTS posthog.events_json_ws_mv;       -- MV first: no double-write window
   DROP TABLE IF EXISTS posthog.kafka_events_json_ws;
   -- CREATE the new kafka table (from step 1)
   -- CREATE the new MV (from step 1)
   ```

   Neither object is replicated → no ZK metadata, no `SYNC` needed. Offsets only commit
   on successful MV insert, so the gap loses nothing; consumption resumes from the last
   committed offset.

4. - [ ] Per host before moving on: `system.kafka_consumers` shows the consumer active,
         no rows in `system.errors` for `NO_SUCH_COLUMN_IN_TABLE`/`THERE_IS_NO_COLUMN`, and
         inserts visible in `writable_events` (`system.query_log` or part churn on
         `sharded_events`).
5. - [ ] Watch for 30 minutes after the last host, **both**:
   - end-to-end ingestion lag (the usual dashboards), and
   - the Distributed async-insert queue — during the 2026-06-01 incident Kafka lag looked fine while
     CH buffered everything locally:
     `SELECT hostName(), database, table, error_count, data_files FROM clusterAllReplicas('posthog', system.distribution_queue) WHERE data_files > 0`.
6. - [ ] Commit the final `SHOW CREATE TABLE` outputs to `PostHog/clickhouse_schemas`.

Rollback for this phase: re-run step 3 with the **unmodified live DDL captured in §2**
(that is byte-for-byte the recovery performed by hand during the 2026-06-01 incident). The added columns
from §3 are nullable, unreferenced, and harmless — they never need rolling back.

## 5. Slot-assignments table + dictionary (no ingestion impact)

On **every data node** of the main cluster (30 hosts US / 24 EU — loop with the team's
host-runner of choice; the table is intentionally per-host, plain `ReplacingMergeTree`,
no ON CLUSTER, no replication):

```sql
CREATE TABLE IF NOT EXISTS posthog.dmat_slot_assignments (
    team_id UInt64,
    column_index UInt8,
    property_name String,
    version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = ReplacingMergeTree(version)
ORDER BY (team_id, column_index);

CREATE DICTIONARY IF NOT EXISTS posthog.dmat_slot_assignments_dict (
    team_id UInt64,
    column_index UInt8,
    property_name String
)
PRIMARY KEY team_id, column_index
SOURCE(CLICKHOUSE(QUERY 'SELECT team_id, column_index, property_name FROM posthog.dmat_slot_assignments FINAL' USER '<migrations user>' PASSWORD '<from the usual secret store>'))
LIFETIME(MIN 600 MAX 1200)
LAYOUT(COMPLEX_KEY_HASHED());
```

These render from `posthog/models/dmat_slot_assignments/sql.py` — if in doubt, generate
them from a prod-configured shell rather than copying from here.

- [ ] Verify on a sample of hosts: `SELECT dictHas('posthog.dmat_slot_assignments_dict', (toUInt64(2), toUInt8(0)))`
      returns `0` (empty dict resolves, doesn't throw).

## 6. Before the first workflow run on cloud

The weekly backfill submits an `ALTER TABLE sharded_events UPDATE dmat_string_N = ...
WHERE dictHas(...)` bounded only by team
(`posthog/temporal/backfill_materialized_property/activities.py`,
`_build_dict_backed_update_command`). The missing time bound is deliberate: dmat columns
have no DEFAULT expression to fall back on (the meaning of a column is per-team, via the
dictionary), so historical correctness requires backfilling all of the team's rows — old
parts included.

**Precedent:** this is the same shape as the scheduled person-overrides squash
(`posthog/dags/person_overrides.py` — an unbounded
`UPDATE person_id = dictGet(...) WHERE dictHas(...)` over `sharded_events`), which runs
routinely and completed successfully on the post-migration US cluster on 2026-06-08. So
unbounded single-column UPDATEs over full history are established practice. The
mutations that stuck during the 2026-06-01 incident were `DROP COLUMN`s, whose
part-rewrite path failed on old parts that physically lack `inserted_at`
(`NOT_FOUND_COLUMN_IN_BLOCK`, partitions ~2020–2023, observed on EU); a single-column
UPDATE does not rebuild unrelated skip indexes on wide parts, which is consistent with
the squash passing where the DROPs failed.

Per region, before enabling slots for the first cloud team:

- [ ] Confirm the person squash has completed on this cluster since its last topology
      migration (Dagster `squash_person_overrides` run history). US: confirmed
      2026-06-08. EU: outstanding — and EU is where the affected parts were
      demonstrated. If there is no green post-migration squash, first run one
      dmat-shaped UPDATE restricted to a single partition that contains affected parts
      (find them with the query below) and watch it complete. If it fails, the fixes
      are repairing the parts (per-partition `MATERIALIZE COLUMN inserted_at`, or an
      `ALIAS NULL` rewrite) or adding a backfill floor — noting a floor changes
      semantics (rows below it read NULL once the slot is `READY`, so it needs a
      read-path answer too).
- [ ] Coordinate the weekly run with the squash/deletes mutation calendar —
      `sharded_events` mutations contend (the 2026-06-07 squash run failed because
      earlier backfill mutations were still in flight). Don't run the dmat backfill
      concurrently with squash or the post-squash deletes.
- [ ] Check disk headroom on every shard before submitting — part rewrites need
      transient space (incident-window backfills caused disk pressure on two shards).

Query for old parts missing `inserted_at` (per region):

```sql
SELECT partition_id, count() AS parts_missing_inserted_at
FROM cluster('posthog', system.parts_columns)
WHERE database = 'posthog' AND table = 'sharded_events' AND active
  AND part_name NOT IN (
      SELECT part_name FROM cluster('posthog', system.parts_columns)
      WHERE database = 'posthog' AND table = 'sharded_events' AND column = 'inserted_at'
  )
GROUP BY partition_id ORDER BY partition_id;
```

## 7. Feature validation (after the §6 checks)

1. Assign a dmat slot to one dogfood team (team 2) via the product flow; confirm the
   Postgres `MaterializedColumnSlot` row reaches `READY`/`BACKFILL`.
2. Confirm new events for that team land with `dmat_string_<n>` populated (plugin-server
   includes the value once the slot is live).
3. Trigger the weekly workflow manually for that team only. Watch:
   - `populate_slot_assignments` succeeds on all data hosts and the dictionary reload
     shows rows (`SELECT count() FROM dmat_slot_assignments` per host);
   - the mutation on the ClickHouse mutations monitor dashboard (Grafana
     `clickhouse-mutations-monitor`) — progressing on every shard, no
     `latest_fail_reason`;
   - `KILL MUTATION WHERE mutation_id = '...'` is the abort lever (it was used during
     the 2026-06-01 incident). Killing leaves the column partially backfilled, but that is invisible to
     queries: the HogQL read path only swaps a property to its dmat column once the slot
     reaches `READY` (`posthog/hogql/transforms/property_types.py`), and a killed
     backfill leaves the slot in `BACKFILL`, still reading from the JSON blob.
4. Only after one clean cycle, open slots to further teams.
