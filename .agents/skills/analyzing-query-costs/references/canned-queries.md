# Canned queries for query-cost analysis

All queries run via `posthog:execute-sql` (or the equivalent SQL tool exposed by the current agent runtime) in the internal analytics project (project 2).
They use the example window `2026-06-14 → 2026-07-14` (exclusive end) — derive a currently covered window from §0 and substitute it everywhere; keep per-branch date filters inside every UNION branch.
The cost expression is inlined in each query so they run standalone after one find-and-replace:

```sql
sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}
```

`{read_usd_per_gb}` ($ per GB read) and `{cpu_usd_per_sec}` ($ per CPU-second) are the internal cost-model unit rates — they are not committed to this public repo, so get the current values from the requester and substitute them everywhere before running.
Read bytes and CPU are the only priced terms — `memory_usage` and the S3 transfer counters exist in these tables but aren't priced, and inter-node network counters aren't exported (details in SKILL.md → Cost model).

## 0. Coverage check (run first, per region)

```sql
SELECT min(event_date) AS min_date, max(event_date) AS max_date
FROM query_log_archive_us
WHERE event_date >= '2026-01-01'
```

Repeat for `query_log_archive_eu`. Pick a window fully covered by both regions.

## 1. Totals per region

```sql
SELECT region,
       count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6, 0) AS cpu_sec,
       round(sum(read_bytes)/1e9*{read_usd_per_gb}, 0) AS read_cost_usd,
       round(sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cpu_cost_usd,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM (
    SELECT 'us' AS region, read_bytes, ProfileEvents_OSCPUVirtualTimeMicroseconds
    FROM query_log_archive_us
    WHERE event_date >= '2026-06-14' AND event_date < '2026-07-14'
    UNION ALL
    SELECT 'eu' AS region, read_bytes, ProfileEvents_OSCPUVirtualTimeMicroseconds
    FROM query_log_archive_eu
    WHERE event_date >= '2026-06-14' AND event_date < '2026-07-14'
)
GROUP BY region
```

Everything below reuses this two-region FROM block; only the projected columns change.
The `/* §1 FROM block, each branch projecting: ... */` comments are assembly instructions, not executable SQL: replace each one with the two-branch UNION from §1, project the listed columns in the SELECT of **both** branches, and apply the same date (and any dimension) filters to each branch.
The inner SELECTs must include **every column referenced outside the subquery** — an outer `WHERE user = ...` fails with "Unable to resolve field" unless `user` is projected in both branches.

## 2. By ClickHouse user (app / api / dagster / cache_warmup / cohorts / ...)

```sql
SELECT region, user, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: region, user, read_bytes, ProfileEvents_OSCPUVirtualTimeMicroseconds */ )
GROUP BY region, user
ORDER BY cost_usd DESC
LIMIT 30
```

## 3. By workload kind

```sql
SELECT lc_kind, lc_workload, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: lc_kind, lc_workload, read_bytes, ProfileEvents_... */ )
GROUP BY lc_kind, lc_workload
ORDER BY cost_usd DESC
LIMIT 30
```

`request`+`ONLINE` is interactive traffic; everything else is background/automated.
Flag `temporal`+`ONLINE` if large (background work on the online tier).

## 4. Canonical breakdown: product × feature (disjoint buckets)

```sql
SELECT lc_product, lc_feature, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: lc_product, lc_feature, read_bytes, ProfileEvents_... */ )
GROUP BY lc_product, lc_feature
ORDER BY cost_usd DESC
LIMIT 35
```

## 5. Temporal workflows (drill-down — rows here are already inside §4's buckets; don't add the two together)

```sql
SELECT lc_temporal__workflow_type AS workflow, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: lc_kind, lc_temporal__workflow_type, read_bytes, ProfileEvents_... */ )
WHERE lc_kind = 'temporal'
GROUP BY workflow
ORDER BY cost_usd DESC
LIMIT 25
```

## 6. Dagster jobs

```sql
SELECT job, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: lc_dagster__job_name AS job, lc_kind, user, read_bytes, ProfileEvents_... */ )
WHERE lc_kind = 'dagster' OR user = 'dagster'
GROUP BY job
ORDER BY cost_usd DESC
LIMIT 25
```

## 7. Daily trend by bucket — one-off vs steady vs growing

Adapt the `multiIf` arms to whatever §4/§5 surfaced as the top buckets:

```sql
SELECT event_date,
       multiIf(
           lc_product = 'web_analytics' AND lc_feature = 'backfill', 'wa_backfill',
           lc_product = 'warehouse' AND lc_feature = 'data_modeling', 'dw_data_modeling',
           lc_product = 'internal' AND lc_feature = 'management_command', 'internal_mgmt_cmd',
           lc_product = 'experiments' AND lc_feature = 'management_command', 'experiments_mgmt_cmd',
           lc_feature = 'cache_warmup', 'cache_warmup',
           'other') AS bucket,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: event_date, lc_product, lc_feature, read_bytes, ProfileEvents_... */ )
GROUP BY event_date, bucket
ORDER BY event_date, bucket
LIMIT 250
```

## 8. Cost per team (which teams spend the most)

```sql
SELECT region, team_id, any(lc_org_id) AS org_id, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: region, team_id, lc_org_id, read_bytes, ProfileEvents_... */ )
GROUP BY region, team_id
ORDER BY cost_usd DESC
LIMIT 30
```

`team_id = 0` is infra (backfills, usage reports, monitoring).
Team ids collide across regions — for anything org-level, use the joins below rather than raw team ids.

## 9. Free vs paying split (full attribution join)

```sql
SELECT multiIf(
           c.team_id = 0 OR c.team_id IS NULL, 'infra (no team attribution)',
           t.organization_id = '4dc8564d-bd82-1065-2f40-97f7c50f67cf', 'posthog internal org',
           t.id IS NULL, 'deleted/unknown team',
           a.mrr > 0, 'paying customer',
           'free customer') AS bucket,
       uniq(tuple(c.region, c.team_id)) AS teams, sum(c.queries) AS queries,
       round(sum(c.read_gb), 0) AS read_gb,
       round(sum(c.read_gb)*{read_usd_per_gb} + sum(c.cpu_sec)*{cpu_usd_per_sec}, 0) AS cost_usd
FROM (
    SELECT region, team_id, count() AS queries, sum(read_bytes)/1e9 AS read_gb,
           sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6 AS cpu_sec
    FROM ( /* §1 FROM block, each branch projecting: 'us'/'eu' AS region, team_id, read_bytes, ProfileEvents_... */ )
    GROUP BY region, team_id
) AS c
LEFT JOIN (SELECT id, app_region, organization_id FROM all_posthog_team) AS t
    ON t.id = c.team_id AND t.app_region = c.region
LEFT JOIN (SELECT organization_id, max(mrr) AS mrr FROM accounts_replacement_v2 GROUP BY organization_id) AS a
    ON a.organization_id = t.organization_id
GROUP BY bucket
ORDER BY cost_usd DESC
```

Region labels in the union must be lowercase to match `app_region`.

## 10. Top orgs by cost, with MRR (cost ÷ MRR is the pricing-conversation signal)

Same join as §9, but grouped by org, with team 0 excluded inside the per-team subquery, and with **PostHog's own org excluded from the ranking** (report it separately as internal dogfooding). The `coalesce` keeps deleted-team rows visible as a blank org instead of silently dropping them:

```sql
SELECT t.organization_id AS org_id, any(a.name) AS org_name, max(a.mrr) AS mrr,
       any(a.customer_stage) AS stage, uniq(tuple(c.region, c.team_id)) AS teams, sum(c.queries) AS queries,
       round(sum(c.read_gb), 0) AS read_gb,
       round(sum(c.read_gb)*{read_usd_per_gb} + sum(c.cpu_sec)*{cpu_usd_per_sec}, 0) AS cost_usd
FROM (
    SELECT region, team_id, count() AS queries, sum(read_bytes)/1e9 AS read_gb,
           sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6 AS cpu_sec
    FROM ( /* §1 FROM block, each branch projecting: 'us'/'eu' AS region, team_id, read_bytes, ProfileEvents_... */ )
    WHERE team_id != 0 AND team_id IS NOT NULL
    GROUP BY region, team_id
) AS c
LEFT JOIN (SELECT id, app_region, organization_id FROM all_posthog_team) AS t
    ON t.id = c.team_id AND t.app_region = c.region
LEFT JOIN (SELECT organization_id, any(name) AS name, max(mrr) AS mrr, any(customer_stage) AS customer_stage
           FROM accounts_replacement_v2 GROUP BY organization_id) AS a
    ON a.organization_id = t.organization_id
WHERE coalesce(t.organization_id, '') != '4dc8564d-bd82-1065-2f40-97f7c50f67cf'
GROUP BY org_id
ORDER BY cost_usd DESC
LIMIT 20
```

## 11. Top free orgs (query-limit candidates)

§10, with the outer `WHERE` extended to:

```sql
WHERE t.id IS NOT NULL
  AND (a.mrr = 0 OR a.mrr IS NULL)
  AND t.organization_id != '4dc8564d-bd82-1065-2f40-97f7c50f67cf'
```

## 12. Failed-query cost (overlapping slice — these rows are also inside §4's buckets)

```sql
SELECT exception_name, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: type, exception_name, read_bytes, ProfileEvents_... */ )
WHERE type != 'QueryFinish'
GROUP BY exception_name
ORDER BY cost_usd DESC
LIMIT 15
```

## 13. TOO_MANY_BYTES attribution — find the retry loops

```sql
SELECT lc_product, lc_feature, lc_kind, uniq(tuple(region, team_id)) AS teams, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: lc_product, lc_feature, lc_kind, region, team_id, exception_name, read_bytes, ProfileEvents_... */ )
WHERE exception_name = 'TOO_MANY_BYTES'
GROUP BY lc_product, lc_feature, lc_kind
ORDER BY cost_usd DESC
LIMIT 15
```

Many kills + few teams in one bucket = a scheduled job re-running a query that will never fit the byte limit.
Count teams as `uniq(tuple(region, team_id))` (as §9/§10 do) — numeric team ids collide across regions, so plain `uniq(team_id)` merges unrelated US/EU teams into one.

## 14. Access method × chargeable

```sql
SELECT lc_access_method, lc_chargeable, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM ( /* §1 FROM block, each branch projecting: lc_access_method, lc_chargeable, read_bytes, ProfileEvents_... */ )
GROUP BY lc_access_method, lc_chargeable
ORDER BY cost_usd DESC
LIMIT 15
```

Empty access method = logged-in web + background. `sharing_token` = anonymous public embeds — unbilled, cache-friendly.

## 15. Per-org drill-down (what drives one org's cost) — one query per region

```sql
SELECT t.organization_id AS org, c.lc_product AS product, c.lc_feature AS feature,
       count() AS queries,
       round(sum(c.read_bytes)/1e9, 0) AS read_gb,
       round(sum(c.read_bytes)/1e9*{read_usd_per_gb} + sum(c.ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM query_log_archive_us AS c
INNER JOIN (
    SELECT id, organization_id FROM all_posthog_team
    WHERE app_region = 'us' AND organization_id IN ('<org-uuid-1>', '<org-uuid-2>')
) AS t ON c.team_id = t.id
WHERE c.event_date >= '2026-06-14' AND c.event_date < '2026-07-14'
GROUP BY org, product, feature
ORDER BY cost_usd DESC
LIMIT 30
```

## 16. Identify an anonymous workload (blank `lc_name`/`lc_id`) — narrow window first

Management-command and temporal rows usually have blank `lc_name`; `lc_query_type` names the code path.
Full-window versions of this can time out — one region × one week is cheap and usually enough:

```sql
SELECT query_kind, lc_query_type, lc_temporal__workflow_type, uniq(team_id) AS teams, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd
FROM query_log_archive_us
WHERE event_date >= '2026-07-01' AND event_date < '2026-07-08'
  AND lc_product = 'internal' AND lc_feature = 'management_command'
GROUP BY query_kind, lc_query_type, lc_temporal__workflow_type
ORDER BY cost_usd DESC
LIMIT 15
```

## 17. Month-over-month trajectory (per-day normalized — months can be partially covered)

Deliberately single-region: the two archives start on different dates (§0), so a cross-region union over months mixes unequal coverage into misleading totals.
Run it once per region (swap the table name) and report regions separately — only union regions for a window both fully cover.

```sql
SELECT toStartOfMonth(event_date) AS month, count() AS queries,
       round(sum(read_bytes)/1e9, 0) AS read_gb,
       round(sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}, 0) AS cost_usd,
       round((sum(read_bytes)/1e9*{read_usd_per_gb} + sum(ProfileEvents_OSCPUVirtualTimeMicroseconds)/1e6*{cpu_usd_per_sec}) / uniq(event_date), 0) AS cost_per_day
FROM query_log_archive_us
WHERE event_date >= '2026-05-01' AND event_date < '2026-07-15'
GROUP BY month
ORDER BY month
```

Quote `cost_per_day`, and note how many days each month actually has (`uniq(event_date)`).
