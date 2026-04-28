---
name: query-clickhouse-via-metabase
description: >
  Run ClickHouse `system.query_log` analysis via the internal Metabase API.
  Use when investigating slow queries, materialization candidates, per-team
  query performance, ClickHouse cost or memory issues, or any system.query_log
  question. Covers prod-us and prod-eu, SSO-gated cookie auth via `hogli`,
  and ready-to-run query patterns.
---

# Querying ClickHouse via Metabase

PostHog's production ClickHouse clusters are reachable for ad-hoc analysis through
internal Metabase instances. Both Metabases sit behind an AWS ALB with Cognito
OAuth, so authentication is **SSO-gated** — Metabase API keys alone won't work.

This skill is for `system.query_log` analysis from inside the posthog repo.
For pre-built canned queries (slow query summaries, materialization analysis),
see the `query-performance-analysis` repo, which is the source of truth for
those and uses the same Metabase API surface.

## Environment

| Region | Metabase URL                           | ClickHouse DB ID for `query_log`       |
| ------ | -------------------------------------- | -------------------------------------- |
| US     | `https://metabase.prod-us.posthog.dev` | `42`                                   |
| EU     | `https://metabase.prod-eu.posthog.dev` | `35` (query tier) — or `2` (data tier) |

For `query_log` analysis, **use `35` on EU**. The `2` data-tier DB exists for
direct table reads (events, persons, etc.) and is only needed when you're
querying production data, not the logs.

EU's Metabase also exposes additional databases that may be useful for
broader investigations (not `query_log`):

- DB `100` — ClickHouse ingestion layer
- DB `70` — ClickHouse migrations EKS
- DB `34` — PostgreSQL (the PostHog app DB)

US Metabase only exposes one ClickHouse DB (`42`); other backends are
queried via separate datasources you'll discover from `/api/database`.

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

# In scripts: read the cached cookie header for the region you're querying.
COOKIE_HEADER="$(hogli metabase:cookie --region us)"
```

If the cookie has expired, `hogli metabase:cookie --check` exits non-zero
with a "no longer valid — run `hogli metabase:login`" message. **Prompt the
user to run `hogli metabase:login` themselves** — the harness blocks Keychain
access from agent shells, so the user has to authenticate interactively.

## Running an ad-hoc query

Pick the region's DB ID and base URL, build the JSON payload, POST to
`/api/dataset`. The cookie header is the only auth.

**Important:** the cookie cache is per-region. When switching regions,
update **all four** of `REGION`, `DB_ID`, `BASE`, and re-fetch
`COOKIE_HEADER`. Mixing a US cookie with an EU URL fails at the ALB.

```bash
# US
REGION=us; DB_ID=42; BASE="https://metabase.prod-us.posthog.dev"
# EU (query_log lives in DB 35)
# REGION=eu; DB_ID=35; BASE="https://metabase.prod-eu.posthog.dev"

COOKIE_HEADER="$(hogli metabase:cookie --region $REGION)"

python3 -c "
import json, sys
print(json.dumps({
    'database': int(sys.argv[1]),
    'type': 'native',
    'native': {'query': sys.stdin.read(), 'template-tags': {}}
}))
" "$DB_ID" <<'SQL' | curl -sS -X POST \
    -H "Cookie: $COOKIE_HEADER" \
    -H "Content-Type: application/json" \
    -d @- \
    "$BASE/api/dataset"
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

## What counts as a slow query

```sql
query_duration_ms > 30000
OR exception_code IN (159, 160, 241)
```

| Code | Meaning               |
| ---- | --------------------- |
| 159  | TIMEOUT_EXCEEDED      |
| 160  | TOO_SLOW              |
| 241  | MEMORY_LIMIT_EXCEEDED |

## Useful query patterns

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
