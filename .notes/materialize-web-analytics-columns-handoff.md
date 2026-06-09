# Handoff: materialize `$timezone_offset` + `$browser_language` (events)

**Owner to action:** ClickHouse team (owns the `events` table + the Dagster job).
**Why:** the Web analytics `Timezone` and `Language` breakdowns read these event
properties raw via `JSONExtract(properties, …)`. With no materialized column, the
lazy precompute insert scans the whole `properties` blob and OOMs (42 GiB) on
high-volume teams, then falls back to a raw query that times out at 60s. Both
breakdowns have broad real usage (600+ teams each in 7d), so materializing them
clears the timeouts for everyone.

`$session_entry_referrer` (InitialReferringURL) is intentionally NOT in this list —
near-zero usage; handled by dropping it from the eager warmer (PR #62237).

## How (no code PR — it's the existing Dagster job)

Run the `create_materialized_column` job (`posthog/dags/create_materialized_column.py`)
from the Dagster launchpad with this run config. Dry-run first.

```yaml
ops:
  create_materialized_columns_op:
    config:
      table: events
      table_column: properties
      properties:
        - '$timezone_offset'
        - '$browser_language'
      backfill_period_days: 90 # >= the 28d warm window; 90 matches MAX_PRECOMPUTE_DAYS
      is_nullable: true
      dry_run: true # 1) dry-run, confirm intended DDL; 2) re-run with false
```

Steps: launch with `dry_run: true` → confirm the planned column adds/backfill →
re-launch with `dry_run: false` → let the backfill complete (heavy CH disk I/O on
sharded_events; coordinate timing with the CH team).

## Verify after the real run

1. Columns exist on every shard:

```sql
SELECT name, default_kind, substring(default_expression,1,60) AS def
FROM clusterAllReplicas(posthog, system, columns)
WHERE database='default' AND table='sharded_events'
  AND name IN ('mat_$timezone_offset','mat_$browser_language')
GROUP BY name, default_kind, def;
```

2. Timezone/Language lazy inserts stop OOMing and start succeeding (team 2):

```sql
SELECT JSONExtractString(log_comment,'query_type') AS qt,
       count() AS cnt, countIf(exception_code=241) AS ooms, countIf(exception_code=159) AS timeouts
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 2 HOUR
  AND JSONExtractInt(log_comment,'team_id')=2
  AND JSONExtractString(log_comment,'query_type') IN
      ('web_stats_Timezone_lazy_insert','web_stats_Language_lazy_insert')
  AND is_initial_query
GROUP BY qt;   -- expect ooms=0, timeouts=0 after backfill
```

3. Eager warmer run goes to warmed=23/failed=0 once #62237 (drop InitialReferringURL)
   AND this materialization both land (Loki: `eager_baseline_warming_complete`).

## Notes / caveats

- Blast radius is global: 2 new columns on every event row going forward + 90d backfill.
- The auto-materializer didn't catch these because the lazy insert fails with 241 (OOM),
  and the analyzer only acts on 159/160 (timeout/too-slow). The raw-fallback timeouts (159)
  are the only signal it could use, and it hasn't acted — hence the manual run.
