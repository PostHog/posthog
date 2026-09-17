---
name: querying-production-databases-via-metabase
description: >
  Runs read-only production database analysis through PostHog's internal
  Metabase instances. Use for ClickHouse query logs, slow query cost, Postgres
  query plans, index selection, or tenant-size analysis. Covers US and EU
  database discovery, SSO login through `hogli`, safe query rules, and query
  patterns for both engines.
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
- **Postgres** (the app database) — the real query plan for an app query, and
  how a per-project table's rows spread across the fleet.

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

## Running a ClickHouse query

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

## Postgres app database

Use the Postgres connection when a Django request spends time in the app database.
Production data and statistics can select a different plan from local data.

Discover the current database IDs and select the Postgres app database:

```bash
hogli metabase:databases --region us
```

The list can also contain ingestion and migration databases.
Use [`profiling-slow-api-endpoints`](../profiling-slow-api-endpoints/SKILL.md) for the investigation workflow.

### Safety

The Metabase connection uses a shared read replica.
Run only `SELECT` and `EXPLAIN` statements.
Do not run writes or schema changes.
Start with `EXPLAIN`, which does not run the query.
`EXPLAIN ANALYZE` runs the query, so use it only for a narrow, safe `SELECT`.
Keep the endpoint's filters, order, and limit because they can change the plan.

A count grouped by tenant can scan a full table even when its result has a limit.
Prefer an existing aggregate or another source approved by the database owner.
For one tenant, bound the work inside the count:

```sql
SELECT count(*)
FROM (
    SELECT 1
    FROM <table>
    WHERE <tenant_key> = <tenant_id>
    LIMIT <threshold_plus_one>
) AS bounded_rows
```

Results can contain customer identifiers, query text, and private scale data.
Do not copy them into public code, tests, pull requests, issues, or comments.
Use placeholders and broad data shapes in public output.

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

| Symptom                        | Cause                                | Fix                                                              |
| ------------------------------ | ------------------------------------ | ---------------------------------------------------------------- |
| HTTP 302 to `/auth/...`        | Cookie expired or missing            | Tell user to run `hogli metabase:login --region <region>`        |
| HTTP 401                       | Cookie rejected by ALB               | Same as 302                                                      |
| `"status": "failed"` + `error` | Database error (syntax, table, etc.) | Read `error`; fix SQL                                            |
| Hangs / timeout                | Wide `query_log` scan                | Narrow `event_time` range, add `team_id` filter, use `cluster()` |

## ClickHouse investigation workflow

1. **Frame the question.** Slow per-team? Specific query pattern? Cost/memory regression?
2. **Pick the smallest time window** that still answers the question — `query_log` is large; default to 1h–24h, expand only when needed.
3. **Filter to `type = 'QueryFinish'`** for "what actually ran" — there are also `QueryStart` and `ExceptionBeforeStart` rows.
4. **Group then drill in.** First a per-team or per-pattern aggregate, then `WHERE` by the worst offender to see individual queries.
5. **Capture `query_id` examples** in any writeup so reviewers can pull the full row from `query_log` themselves.

## Known limitations

- **Metabase response timeout.** Default is ~60s for native queries; very wide scans will be cut off. Narrow time range or use sampled tables.
- **`log_comment` JSON drift.** New fields appear over time; `JSONExtractString(log_comment, 'foo')` returns `''` if missing — always include an `IS NOT NULL` / `!= ''` guard if filtering on it.
- **Cookie scope.** Each region has its own cookie cache. Run `hogli metabase:login --region <region>` for every region you need; `--region` is required.
