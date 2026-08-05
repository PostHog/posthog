---
name: querying-tophog
description: >
  Query tophog — the ingestion pipeline's heavy-hitter store in ClickHouse — to
  identify hot or expensive actors (team_id, distinct_id, session_id,
  partition) during incident triage. Use when investigating ingestion lag, a
  hot or lagging Kafka partition, expensive person processing, merge storms,
  or any "which team or distinct_id is causing this" question. Covers the
  internal Metabase access path (SSO via hogli), the tophog schema, and the
  cost-vs-volume query lens. Internal-only: results contain cross-customer
  identifiers.
---

# Querying tophog

tophog is the ingestion pipeline's heavy-hitter tracker: workers accumulate
per-key aggregates (counts, timers) in memory and periodically flush them to
the `tophog` ClickHouse table via Kafka (`clickhouse_tophog` topic). It answers
"which actor is responsible" questions that fleet-level Prometheus metrics
cannot — per-metric label cardinality is unbounded (`distinct_id`,
`session_id`), so this data lives only in ClickHouse. Retention is 30 days.

The staff-only Django admin has a dashboard over it, but for agent-driven
triage query it directly through the internal Metabase.

## Access — internal Metabase, never Grafana

The production ClickHouse clusters hold customer data, so there is
deliberately **no ClickHouse datasource for agents in Grafana**. The
sanctioned path is the internal Metabase using the **engineer's own SSO
session** — per-person identity, attributable in Metabase's query history, no
standing credential. General mechanics live in the
`query-clickhouse-via-metabase` skill; the short version:

1. **The user must run login themselves** (the agent shell cannot access the
   Keychain): `hogli metabase:login --region eu` (or `us`). macOS will prompt
   about "Chrome Safe Storage" — that's `browser_cookie3` decrypting the
   browser's cookie store to capture the SSO session; one-time Allow is the
   right choice.
2. Discover the database id — it is not stable across Metabase rebuilds:

   ```bash
   hogli metabase:databases --region eu
   ```

   Pick **"PostHog ClickHouse PROD <REGION> Data Tier"** (the data tier, not
   the query tier — tophog lives with the events data).

3. Run queries; the cookie is read internally and never enters the transcript:

   ```bash
   hogli metabase:query --region eu --database-id <id> <<'SQL'
   SELECT ...
   SQL
   ```

## Schema

Table `tophog` (Distributed over `sharded_tophog`), ordered by
`(pipeline, lane, metric, timestamp, key)`, partitioned by day:

| Column      | Type                   | Notes                                                                                                |
| ----------- | ---------------------- | ---------------------------------------------------------------------------------------------------- |
| `timestamp` | DateTime64(6)          | Flush-window time; always bound it (daily partitions)                                                |
| `metric`    | LowCardinality(String) | See inventory below                                                                                  |
| `type`      | LowCardinality(String) | Aggregation semantics: `sum` (default), `max`, `avg`                                                 |
| `key`       | Map(String, String)    | The actor: access as `key['team_id']`, `key['distinct_id']`, `key['partition']`, `key['session_id']` |
| `value`     | Float64                | The aggregated value for this flush window                                                           |
| `count`     | UInt64                 | Observations in the window                                                                           |
| `pipeline`  | LowCardinality(String) | e.g. `analytics`                                                                                     |
| `lane`      | LowCardinality(String) | `main`, `overflow`, `historical`, `async`, `turbo`                                                   |
| `labels`    | Map(String, String)    | Extra non-key labels                                                                                 |

One row is one worker's flush window for one (metric, key) — always aggregate
on read. Read-side semantics per `type` (matches the admin dashboard):

```sql
CASE type
    WHEN 'max' THEN max(value)
    WHEN 'avg' THEN sum(value * count) / sum(count)
    ELSE sum(value)
END
```

## Metric inventory — discover live, don't trust lists

Metrics are defined inline in the ingestion pipelines (grep `topHog(` /
`timer(` / `sum(` in `nodejs/src/ingestion/pipelines/analytics/`), so the set
evolves. Always start with discovery:

```sql
SELECT metric, type, count() AS rows, sum(count) AS observations
FROM tophog
WHERE timestamp > now() - INTERVAL 1 HOUR
GROUP BY metric, type
ORDER BY metric
```

As of 2026-07-06 (master), the analytics metrics include
`process_persons_time` (timer; key: team_id, distinct_id, partition),
`emitted_events[_per_distinct_id|_per_partition]`,
`transformations_run[_per_partition]`,
`events_dropped_by_transformation[_per_partition]`,
`merge_events_per_distinct_id` (merge-intent events: `$create_alias` /
`$merge_dangerously` with alias, `$identify` with `$anon_distinct_id`),
`group_identify_events_per_distinct_id`, `resolved_teams`, and session-replay
`*_by_session_id` timers.

**Dimensions are deploy-gated and rows are immutable**: the `partition` key on
`process_persons_time` and the merge/group-identify metrics merged 2026-07-06
and only exist in data written after that deploy reaches the environment.
Check before relying on them:

```sql
SELECT countIf(key['partition'] != '') AS with_partition, count() AS total
FROM tophog
WHERE timestamp > now() - INTERVAL 1 HOUR AND metric = 'process_persons_time'
```

## The lens: cost vs volume

This is the load-bearing idea. Volume ranking finds **busy** actors; cost
ranking finds **slow** ones — and a single lagging partition is usually a
_cost_ problem (a real incident: the top-cost actor was invisible in every
volume view). Rank by summed timer value, and compute the per-event ratio to
classify what you found:

| Pattern                      | Reading                                                                                              |
| ---------------------------- | ---------------------------------------------------------------------------------------------------- |
| High events, normal ms/event | Hot key (volume) — overflow/rebalance is the lever                                                   |
| Low events, high ms/event    | Expensive actor — fat person properties, merge-heavy, or contended writes; scaling out will not help |

## Canned queries

Top actors by person-processing cost (the incident query):

```sql
SELECT
    key['team_id'] AS team_id,
    key['distinct_id'] AS distinct_id,
    round(sum(value)) AS total_ms,
    sum(count) AS events,
    round(sum(value) / sum(count), 1) AS ms_per_event,
    arraySort(groupUniqArray(lane)) AS lanes
FROM tophog
WHERE timestamp > now() - INTERVAL 1 HOUR
  AND metric = 'process_persons_time'
GROUP BY team_id, distinct_id
ORDER BY total_ms DESC
LIMIT 10
```

Scoped to one lagging partition (data written after the partition dimension
deployed):

```sql
-- add to WHERE:
  AND key['partition'] = '434'
```

Merge storms (merges are the classic person-processing cost driver):

```sql
SELECT key['team_id'] AS team_id, key['distinct_id'] AS distinct_id,
       key['partition'] AS partition, sum(value) AS merge_events
FROM tophog
WHERE timestamp > now() - INTERVAL 1 HOUR
  AND metric = 'merge_events_per_distinct_id'
GROUP BY team_id, distinct_id, partition
ORDER BY merge_events DESC
LIMIT 10
```

Generic top-10 per metric with correct type semantics (the admin dashboard's
query shape) — filter by `pipeline` / `lane` as needed:

```sql
SELECT metric, type, key, total, obs
FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY metric, type ORDER BY total DESC) AS rn
    FROM (
        SELECT metric, type, key,
               CASE type
                   WHEN 'max' THEN max(value)
                   WHEN 'avg' THEN sum(value * count) / sum(count)
                   ELSE sum(value)
               END AS total,
               sum(count) AS obs
        FROM tophog
        WHERE timestamp > now() - INTERVAL 1 HOUR
          AND pipeline = 'analytics' AND lane = 'main'
        GROUP BY metric, type, key
    )
)
WHERE rn <= 10
ORDER BY metric, type, rn
```

## Cautions

- **`distinct_id` and `session_id` values are customer PII** (often emails).
  Internal triage use only — never paste them into public PRs, issues, or
  commit messages.
- Always bound `timestamp` — the table is partitioned by day and holds 30
  days.
- Queries run under the engineer's Metabase identity and appear in their
  query history.

## Related

- `monitoring-ingestion-pipeline` — the Grafana-side diagnosis, including the
  single-partition-lag playbook that hands off to this skill for actor
  identification.
- The pganalyze MCP — the next hop when person processing is implicated
  (query-level view of the persons Postgres).
