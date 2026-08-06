# Materialization analysis

Finding properties worth materializing (to stop JSONExtract scans) and materialized columns worth
dropping (to reclaim disk). **Always run on both US and EU**, since they have different materialized
columns and workloads, so the candidate lists differ. Write the result to the private
`PostHog/query-performance-analysis` repo as `analysis/<date>-materialization-candidates.md`.

Run everything via `query-clickhouse-via-metabase`. Split wide column-list checks into batches of ~5-6
to stay under the Metabase response cutoff.

## Step 1: Candidates to materialize

The candidate list is the JSON-extracted property breakdown from `query-patterns.md` §7: which property
names slow queries pull out of a JSON blob, split by `column` (event `properties`, `person_properties`,
or `group_properties`), with the teams driving each. Run that query (widen the window to ~30 days for
materialization, since a property is worth materializing if it is hit consistently). Rank by
`slow_queries` and `teams`; a property hit by many slow queries across several teams is the strongest
candidate. The `column` tells you which blob it lives on, which the dagster job needs (table,
table_column, property).

To recover the table + column for a specific candidate:

```sql
SELECT
    arrayDistinct(extractAll(query, '(\\w+)\\.\\w*properties,\\s*''<PROPERTY>''')) AS table_aliases,
    arrayDistinct(extractAll(query, '\\w+\\.(\\w*properties),\\s*''<PROPERTY>''')) AS columns
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 7 DAY AND query LIKE '%<PROPERTY>%' LIMIT 100
```

## Step 2: What is already materialized

```sql
SHOW CREATE TABLE sharded_events
```

Cross-reference against Step 1 to split "needs materializing" from "bypassing an existing mat column".
A bypass (mat column exists but queries still JSONExtract) usually means the property is accessed as
`JSONExtractString(properties, '$foo')` in user-written HogQL, which creates an `ast.Call` that skips
`visit_property_type()`, rather than `properties.$foo` which materializes. Known sources: HogQL /
DataVisualization nodes and some survey SQL.

## Step 3: Drop candidates

A materialized column is only **safe to drop** when it has zero queries over 30 days **and** zero data.
Usage must be checked across **all** queries, not just slow ones.

```sql
-- usage: does any query reference the column? (targeted countIf per column to avoid timeouts)
SELECT countIf(query LIKE '%mat_<col>%') AS uses
FROM posthog.query_log_archive
WHERE event_time > now() - INTERVAL 30 DAY AND is_initial_query
```

```sql
-- disk size
SELECT name, formatReadableSize(sum(data_compressed_bytes)) AS compressed
FROM clusterAllReplicas(posthog, system, columns)
WHERE table = 'sharded_events' AND name LIKE 'mat_%'
GROUP BY name ORDER BY sum(data_compressed_bytes) DESC
```

```sql
-- data presence before dropping (batch the column list)
SELECT
    countIf(mat_<col> != '') AS nonempty_<col>,
    uniqExactIf(team_id, mat_<col> != '') AS teams_<col>
FROM events
WHERE timestamp > now() - INTERVAL 7 DAY
```

Read data presence from the Distributed `events` table, not `clusterAllReplicas(...)` over the local
`sharded_events`. The Distributed table fans out to one replica per shard, so each row is counted once;
`clusterAllReplicas` hits every replica and multiplies the counts by the replication factor. Use
`clusterAllReplicas` only for non-Distributed system tables (as the disk-size query above does with
`system.columns`).

- Zero queries + zero data → safe to drop.
- Zero queries + active data → risky. Dropping does not lose data (it stays in the JSON blob) but
  re-materializing later needs an expensive backfill. Record as an optional drop with size + team info.

## Step 4: Dagster jobs

These jobs must be run by a human operator with dagster access; you cannot run them yourself. Before
running anything, the operator should sanity-check with #team-clickhouse that the cluster is not in a bad
state (backfills and materializations add load, so they must not land while the cluster is already
struggling). Hand the operator the configs below as a recommendation rather than executing them.

- Create: `create_materialized_column` (team-clickhouse location, per region). Backfilling adds cluster
  load, so schedule for a weekend.
- Drop: `drop_materialized_column` (defaults to `dry_run: true`; minimal impact).

## Report format

Start with four recommendation tables, then dagster configs, then the investigation detail.

New materializations:

| Table | Column | Property | Slow queries (30d) | Teams | Timeouts | Avg read | Max read | Est. column size |

Drop candidates:

| Column | Compressed | Non-empty events | Teams | Safe to drop? |

Put US-new, EU-new, US-drop, EU-drop as separate tables. Optional drops (no queries but active data) go
into the same dagster config as commented-out entries with their size and team info.
