# Follow-up — verify base-runner tagging covers every web analytics entry point

PR #59148 tags `product=WEB_ANALYTICS, feature=QUERY` at the top of
`WebAnalyticsQueryRunner.calculate()`. That covers the standard API path
(`process_query_model` → `query_runner.run` → `calculate`), but it misses any
caller that invokes a runner without going through `calculate()`.

## What to verify before/around rollout

- **Cache warmer / scheduled refresh** — `webAnalyticsQueryWarming` task: does
  it call `.calculate()` or assemble `_calculate()` directly? Same question
  for any team-level periodic refresh of overview/stats-table.
- **Precomputation jobs** — anything in `products/analytics_platform/` that
  builds preagg/lazy tables for web analytics. Tagging may need to happen
  at the job entry too (per-job, not per-runner), since they don't go
  through `calculate()`.
- **External API consumers** — endpoints/SDKs that hit `/api/.../query/` with
  a `kind: Web*Query` payload: do they reach `query_runner.run()`? They
  should, but worth confirming for the `personal_api_key` access path and
  any embed/iframe paths.
- **Dashboard / insight materialized refresh** — if a Web* query is stored
  as an insight and refreshed via insight materialization, the entry point
  may differ.

## Quick check after deploy

Run the post-deploy distribution slice from
`/evaluating-web-analytics-performance`:

```sql
SELECT
    JSONExtractString(log_comment, 'query_type') AS query_type,
    JSONExtractString(log_comment, 'product')    AS product,
    JSONExtractString(log_comment, 'feature')    AS feature,
    JSONExtractString(log_comment, 'kind')       AS kind,
    count() AS cnt
FROM clusterAllReplicas(posthog, system, query_log)
WHERE event_time > now() - INTERVAL 1 HOUR
    AND type = 'QueryFinish'
    AND is_initial_query
    AND JSONExtractString(log_comment, 'query_type') LIKE 'web_%'
GROUP BY query_type, product, feature, kind
ORDER BY query_type, cnt DESC
```

Any row with empty `product` or `feature` for a `web_*` query_type after the
fix lands means there's a bypassing entry point we missed.

## Status

Not blocking the current PR — base-runner tagging is the right primary fix
and covers the dominant API path (verified locally across 11 query types).
This is a "verify and patch holes" follow-up, not a redesign.
