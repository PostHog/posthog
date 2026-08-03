# Persons streaming migration runbook

How a duckling's persons data moves from the Dagster batch backfill
(`duckling_persons_backfill`) to streaming replication (millpond + viaduck).
Read this alongside [README_DUCKLINGS.md](README_DUCKLINGS.md), which covers
the batch system this replaces.

Status: **in progress**. This file is the coordination point for the
cross-repo work; the per-repo pieces are linked at the bottom.

## Why

The batch job re-exports persons daily by `_timestamp` (Kafka ingestion time)
and replaces the day's partition: ClickHouse `FINAL` join, S3 parquet,
ranged `DELETE`, `ducklake_add_data_files`. It works, but data is up to a day
stale, every re-export re-reads full person state, and the delete-then-register
window is not atomic for readers. Streaming lands person changes in the
duckling within minutes.

## What changes shape

The batch table is **denormalized**: one row per `distinct_id`, person
properties stamped on, produced by a `person FINAL ⋈ person_distinct_id2
FINAL` join. Neither millpond (one Kafka topic to one table, insert-only) nor
viaduck (row-level CDC routing, no joins) can produce that shape, so a
streamed duckling carries three objects instead of one table:

| Object | Name (suffixed team `ab12`) | Written by | Shape |
|---|---|---|---|
| Raw persons | `persons_ab12_raw` | viaduck full_cdc, upsert key `(team_id, id)` | Latest version per person, `is_deleted=1` tombstones included |
| Raw distinct-ids | `persons_distinct_ids_ab12_raw` | viaduck full_cdc, upsert key `(team_id, distinct_id)` | Latest mapping per distinct_id, tombstones included |
| Denormalized view | `persons_ab12` (canonical, post-cutover) | nobody (view) | Exactly the batch table's columns, tombstones filtered |

Two things to internalize before touching a team:

1. **Tombstones are rows, not deletes.** The Kafka person changelogs signal
   deletion with `is_deleted=1` upserts; the source lake millpond lands is
   append-only, so viaduck only ever sees inserts and upserts them by key.
   Deleted persons stay physically present in the raw tables and the view
   filters them. Readers querying raw tables directly must filter
   `is_deleted` themselves.
2. **Merges converge through the mapping table.** A person merge moves
   distinct_ids between persons: the distinct-ids changelog emits new
   mapping versions, viaduck upserts them, and the view's join follows the
   new mapping. No cross-tenant routing is involved because merges stay
   within a team.

## Pipeline architecture

```
clickhouse_person topic ─────────┐
                                 ├─► millpond (2 StatefulSets, team allowlist
clickhouse_person_distinct_id ───┘    from the duckgres control plane)
                                             │
                                             ▼
                              shared changelog DuckLake (megaduck)
                                             │
               viaduck full_cdc, 2 pipelines (table_field selects the
               discovery field), route by team_id
                                             │
                                             ▼
                per-duckling persons_<suffix>_raw + persons_distinct_ids_<suffix>_raw
```

The full historical backfill **stays batch**. Kafka retention bounds how far
back millpond can read, and viaduck discovery initializes destinations at the
source head by design. Streaming replaces the daily top-up sensor, not the
initial load.

## Per-team cutover

Prerequisites: the millpond persons pipelines and the viaduck persons
pipelines are deployed (charts values), and the duckgres control plane serves
`persons_distinct_ids_table` in the discovery payload.

1. **Prep the duckling schema.** Run any `duckling_persons_backfill_job`
   partition for the team with:

   ```yaml
   ops:
     duckling_persons_backfill:
       config:
         create_persons_streaming_schema: true
         persons_streaming_view_name: "persons_ab12_streaming"  # scratch name
   ```

   This creates `persons_ab12_raw`, `persons_distinct_ids_ab12_raw`, and a
   validation view at the scratch name. The batch table keeps the canonical
   name, so nothing reader-visible changes.

2. **Point viaduck at the team.** Repoint the team's control-plane
   `persons_table_name` override from `persons_ab12` to `persons_ab12_raw`.
   Discovery then serves the raw names (`persons_ab12_raw` and, by
   derivation, `persons_distinct_ids_ab12_raw`) to the viaduck persons
   pipelines. New destinations initialize at the source head: only changes
   from this moment onward stream.

3. **Final batch top-up.** Run the team's daily partition once more so the
   batch table holds everything up to the streaming cutover point. Expect a
   small gap-or-overlap window either way; the view is idempotent under
   overlap because the raw tables hold latest-per-key, and a gap only means
   minutes of lag, not loss (the changelogs retain days).

4. **Validate.** Compare the batch table against the scratch view:

   ```sql
   SELECT count(*) FROM posthog.persons_ab12;            -- batch
   SELECT count(*) FROM posthog.persons_ab12_streaming;  -- streamed
   ```

   Counts should match within streaming lag. Spot-check a few recently
   updated persons for property freshness.

5. **Swap the view in.** Drop the batch table (or rename it to
   `persons_ab12_batch` for a retention period) and re-run the prep config
   with `persons_streaming_view_name: "persons_ab12"`. Readers keep the same
   table name and columns.

6. **Stop the batch top-up.** Disable warehouse backfill for the team (the
   same control-plane enablement the sensors enumerate), so
   `duckling_persons_daily_backfill_sensor` and the full-backfill sensor stop
   creating partitions for it.

## Rollback

Until step 5, rollback is "do nothing": the batch table is untouched and the
raw tables are inert extra objects. After step 5, rollback is: drop the view,
rename `persons_ab12_batch` back to `persons_ab12`, re-enable backfill for
the team, and run a full-export partition to close any gap. The raw tables
can stay (viaduck keeps them current, harmless) or be dropped.

## Open decisions

- **View naming vs reader migration.** This runbook keeps the canonical name
  on the view so readers never change. The alternative is leaving
  `persons_ab12` on the raw table and migrating readers to a new view name,
  which avoids the drop-and-swap in step 5 but breaks every saved query
  against the batch shape.
- **The viaduck rowid-reuse window.** A delete followed by a recreate of the
  same key inside one viaduck flush window (~2 min) can drop the recreated
  row (known full_cdc issue). Rare for persons, but a person deleted and
  recreated quickly can briefly vanish from the view until the next version
  arrives.
- **Update fan-out cost.** A person property update rewrites one raw row but
  changes N view rows (one per distinct_id). Views make this free at write
  time and slightly more expensive at read time than the batch table. Measure
  on the first high-traffic team before fleet cutover.

## Cross-repo pieces

| Repo | Piece | Status |
|---|---|---|
| posthog (this repo) | Streamed schema DDL + prep config flag + this runbook | this PR |
| duckgres | `persons_distinct_ids_table` in the discovery payload | PR linked in this PR's description |
| viaduck | `discovery.table_field` to select the persons table fields | branch prepared; needs push access |
| millpond | nothing: the persons pipelines are env-var config only | charts values |
| charts | millpond pipelines for the two person topics; viaduck persons pipelines with `table_field` and full_cdc keys | not yet written |
