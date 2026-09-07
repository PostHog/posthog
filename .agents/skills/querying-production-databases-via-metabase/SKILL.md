---
name: querying-production-databases-via-metabase
description: >
  Run read-only analysis against PostHog's production databases through the
  internal Metabase API. Covers ClickHouse `system.query_log` (slow queries,
  materialization candidates, per-team query cost and memory) and the Postgres
  app database (`EXPLAIN (ANALYZE, BUFFERS)` on a real plan, which index the
  planner picks, how a table's rows spread across projects). Use when
  investigating a slow ClickHouse query, a slow Django or Postgres endpoint,
  why the planner prefers one index over another, or how large a per-project
  table is across the fleet. Includes prod-us and prod-eu, SSO-gated cookie
  auth via `hogli`, and ready-to-run query patterns for both engines.
---

# Querying production databases via Metabase

PostHog's production databases are reachable for ad-hoc, read-only analysis
through internal Metabase instances. Both Metabases sit behind an AWS ALB with
Cognito OAuth, so authentication is **SSO-gated** — Metabase API keys alone
won't work.

Two engines are behind the same API surface, and the reason to reach for each
is different:

- **ClickHouse** — `system.query_log` analysis: which queries are slow, what
  they read, who runs them.
- **Postgres** (the app database) — the real query plan for an app query. This
  is the only way to see which index production actually uses, because the
  planner's choice depends on production statistics that a local database does
  not have.

For pre-built canned ClickHouse queries (slow query summaries, materialization
analysis), see the `query-performance-analysis` repo, which is the source of
truth for those and uses the same Metabase API surface.

## Environment

| Region | Metabase URL                           |
| ------ | -------------------------------------- |
| US     | `https://metabase.prod-us.posthog.dev` |
| EU     | `https://metabase.prod-eu.posthog.dev` |

**Database IDs are not stable** — they change when Metabase's metadata DB is
rebuilt or connections are re-added. Never hardcode an ID. Always discover
the current list:

```bash
hogli metabase:databases --region us
hogli metabase:databases --region eu
```

Regional layout (names may vary; re-check with `metabase:databases`):

- **US** exposes one ClickHouse database (used for `query_log` and data reads).
- **EU** exposes two ClickHouse databases — a **query tier** (use for
  `query_log` analysis) and a **data tier** (production reads: events,
  persons, etc.). Pick the one whose name indicates the query tier.
- Both Metabases also expose Postgres databases (the app DB) and, on EU,
  the ingestion-layer and migrations databases.

## Authentication

Use `hogli` to get a valid cookie. It opens the system browser for SSO,
captures cookies from the user's logged-in browser profile, and caches them
at `~/.config/posthog/metabase/cookie-{region}` (mode `0600`).

```bash
# Log in once per region. --region is required (no default — you pick which one).
# Already-valid sessions are fast-pathed (no browser tab opens), so re-running
# is cheap.
hogli metabase:login --region us
hogli metabase:login --region eu
```

**Prompt the user to run `hogli metabase:login` themselves** — the harness
blocks Keychain access from agent shells, so the user has to authenticate
interactively.

### Agents: use `metabase:query`

`hogli metabase:query` reads the cached cookie internally and only emits
results — the session value never appears in the agent's transcript.
`metabase:cookie` exists for humans who want to hand-roll `curl` against
Metabase.

## Running an ad-hoc query

1. Discover the current ClickHouse DB ID: `hogli metabase:databases --region <region>`.
2. Pass that ID into `hogli metabase:query`. Pipe SQL via stdin or `--file`.

```bash
# 1. Find the ClickHouse database ID for your region
hogli metabase:databases --region us
# e.g. output row:  42  ClickHouse  clickhouse

# 2. Run the query. The cookie is read internally; nothing leaks to stdout.
hogli metabase:query --region us --database-id 42 --save /tmp/out.tsv <<'SQL'
SELECT
    JSONExtractInt(log_comment, 'team_id') AS team_id,
    count() AS query_count,
    formatReadableSize(sum(read_bytes)) AS total_bytes
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 1 DAY
    AND is_initial_query
    AND query_duration_ms > 30000
GROUP BY team_id
ORDER BY query_count DESC
LIMIT 20
SQL
```

`clusterAllReplicas(posthog, system, query_log)` is the standard table reference —
it fans out across the cluster.

For large result sets, use `--save <path>` so rows land in a file rather
than streaming through the terminal/transcript. Default output is TSV;
`--format json` gives you the raw `/api/dataset` response body.

If the DB ID is wrong, `metabase:query` exits non-zero with a pointer back
to `metabase:databases`. Fail-fast is intentional — silently querying the
wrong database is worse than failing.

## ClickHouse: what counts as a slow query

```sql
query_duration_ms > 30000
OR exception_code IN (159, 160, 241)
```

| Code | Meaning               |
| ---- | --------------------- |
| 159  | TIMEOUT_EXCEEDED      |
| 160  | TOO_SLOW              |
| 241  | MEMORY_LIMIT_EXCEEDED |

## ClickHouse query patterns

### Top slow queries in the last 24h

```sql
SELECT
    query_id,
    JSONExtractInt(log_comment, 'team_id') AS team_id,
    query_duration_ms,
    formatReadableSize(memory_usage) AS memory,
    formatReadableSize(read_bytes) AS read_bytes,
    exception_code,
    substring(query, 1, 200) AS query_preview
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 1 DAY
    AND type = 'QueryFinish'
    AND (query_duration_ms > 30000 OR exception_code IN (159, 160, 241))
    AND JSONExtractString(log_comment, 'workload') NOT IN ('Workload.OFFLINE', 'OFFLINE')
    AND JSONExtractString(log_comment, 'kind') NOT IN ('temporal')
    AND JSONExtractString(log_comment, 'access_method') NOT IN ('personal_api_key')
    AND is_initial_query
    AND JSONExtractInt(log_comment, 'team_id') != 0
ORDER BY query_duration_ms DESC
LIMIT 100
```

### Per-team query cost summary (7d)

```sql
SELECT
    JSONExtractInt(log_comment, 'team_id') AS team_id,
    count() AS queries,
    countIf(query_duration_ms > 30000) AS slow_queries,
    formatReadableSize(sum(read_bytes)) AS total_read,
    formatReadableSize(max(memory_usage)) AS peak_memory,
    quantile(0.95)(query_duration_ms) AS p95_duration_ms
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 7 DAY
    AND type = 'QueryFinish'
    AND JSONExtractString(log_comment, 'workload') NOT IN ('Workload.OFFLINE', 'OFFLINE')
    AND JSONExtractString(log_comment, 'kind') NOT IN ('temporal')
    AND JSONExtractString(log_comment, 'access_method') NOT IN ('personal_api_key')
    AND is_initial_query
    AND JSONExtractInt(log_comment, 'team_id') != 0
GROUP BY team_id
ORDER BY total_read DESC
LIMIT 20
```

### Look up a specific query by `query_id`

Saved card available in both regions — match the URL to where the query ran:

```text
# US
https://metabase.prod-us.posthog.dev/question/795-look-up-query-by-query-id?query_id=<ID>&include_query_start=No&event_date=<YYYY-MM-DD>

# EU (same card ID may differ — find it in EU Metabase if 795 doesn't resolve)
https://metabase.prod-eu.posthog.dev/question/795-look-up-query-by-query-id?query_id=<ID>&include_query_start=No&event_date=<YYYY-MM-DD>
```

The same can be reproduced programmatically with a `WHERE query_id = '...'`
clause via `/api/dataset` against the right region's DB ID.

## Postgres: the app database

Reach for this when an endpoint is slow and the time sits in a Django query.
An `EXPLAIN` from a local database proves nothing about production: the planner
chooses from production statistics, so the same SQL takes a different plan
against a table with millions of rows spread over thousands of projects.

**The database you get is a read replica. Keep it that way.** Run `SELECT` and
`EXPLAIN` only. Never `UPDATE`, `DELETE`, `INSERT`, or `CREATE INDEX`, even to
"test" one, and never `EXPLAIN ANALYZE` a write — `ANALYZE` executes the
statement.

Discover the Postgres database ID the same way as the ClickHouse one; the list
holds several, so read the names:

```bash
hogli metabase:databases --region us   # the app DB, and on EU also ingestion + migrations
```

### Reading a real plan

Use `EXPLAIN (ANALYZE, BUFFERS)`. `BUFFERS` is what tells you whether the cost
is rows or pages, which is usually the whole answer:

```bash
hogli metabase:query --region us --database-id <postgres-id> <<'SQL'
EXPLAIN (ANALYZE, BUFFERS)
SELECT id, name FROM posthog_eventdefinition
WHERE COALESCE(project_id, team_id) = <project_id>
  AND name ILIKE '%session recording%'
ORDER BY name
LIMIT 26
SQL
```

Read it in this order:

1. **Which index did it use?** An index scoped to the tenant behaves nothing
   like a global index on a searched column. A GIN or trigram index on `name`
   covers every project at once, so a small project still pays to read posting
   lists for the whole table.
2. **Buffers, not rows.** A plan that returns 26 rows while reading tens of
   thousands of pages is reading an index it cannot scope.
3. **Compare plan forms, not just timings.** The lever is usually a predicate
   rewrite that changes which index the planner can reach at all. `ILIKE` can
   use a trigram index; `lower(name) LIKE lower(...)` cannot, so the planner
   falls back to the tenant-scoped index. Run both and put the two timings
   side by side.
4. **Run each form more than once** and say whether the cache was warm. One
   run on a cold cache is not a measurement.

### Sizing a dimension across the fleet

Before you make a plan choice conditional on a number, measure how that number
is distributed. A rewrite that wins for the median project can lose badly for
the largest one, and the largest projects are the ones that notice:

```sql
SELECT COALESCE(project_id, team_id) AS project, count(*) AS definitions
FROM posthog_eventdefinition
GROUP BY 1 ORDER BY definitions DESC LIMIT 20
```

Check both ends: the biggest projects, and the percentile where most projects
actually sit. Pick the threshold from the crossover you measured, then leave
headroom.

### Gotchas

- **Statistics move.** A plan you captured last month can differ today. Re-run
  it rather than trusting a number in an old PR description.
- **Keep the query narrow.** Metabase cuts native queries off at about 60s, and
  an `EXPLAIN ANALYZE` really runs the query on a replica other people use.
- **`ORDER BY` and `LIMIT` change the plan.** Profile the SQL the endpoint
  sends, including its ordering and page size, not a simplified version.
- **A paginated endpoint usually runs the predicate twice**, once to count and
  once to fetch. Halving the predicate cost is worth double what it looks like.

## Parsing Metabase responses

```json
{
  "data": {
    "cols": [{"name": "team_id", "base_type": "type/Integer"}, ...],
    "rows": [[55348, 142, "1.23 TiB"], ...]
  },
  "status": "completed",
  "row_count": 20
}
```

Quick TSV pipe:

```bash
... | python3 -c "
import json, sys
d = json.load(sys.stdin)
cols = [c['name'] for c in d['data']['cols']]
print('\t'.join(cols))
for row in d['data']['rows']:
    print('\t'.join(str(v) for v in row))
"
```

### Error responses

| Symptom                        | Cause                                  | Fix                                                              |
| ------------------------------ | -------------------------------------- | ---------------------------------------------------------------- |
| HTTP 302 to `/auth/...`        | Cookie expired or missing              | Tell user to run `hogli metabase:login --region <region>`        |
| HTTP 401                       | Cookie rejected by ALB                 | Same as 302                                                      |
| `"status": "failed"` + `error` | ClickHouse error (syntax, table, etc.) | Read `error`; fix SQL                                            |
| Hangs / timeout                | Wide `query_log` scan                  | Narrow `event_time` range, add `team_id` filter, use `cluster()` |

## Investigation workflow

1. **Frame the question.** Slow per-team? Specific query pattern? Cost/memory regression?
2. **Pick the smallest time window** that still answers the question — `query_log` is large; default to 1h–24h, expand only when needed.
3. **Filter to `type = 'QueryFinish'`** for "what actually ran" — there are also `QueryStart` and `ExceptionBeforeStart` rows.
4. **Group then drill in.** First a per-team or per-pattern aggregate, then `WHERE` by the worst offender to see individual queries.
5. **Capture `query_id` examples** in any writeup so reviewers can pull the full row from `query_log` themselves.

## Known limitations

- **Metabase response timeout.** Default is ~60s for native queries; very wide scans will be cut off. Narrow time range or use sampled tables.
- **`log_comment` JSON drift.** New fields appear over time; `JSONExtractString(log_comment, 'foo')` returns `''` if missing — always include an `IS NOT NULL` / `!= ''` guard if filtering on it.
- **Cookie scope.** Each region has its own cookie cache. Run `hogli metabase:login --region <region>` for every region you need; `--region` is required.
