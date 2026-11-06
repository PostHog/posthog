---
name: profiling-slow-api-endpoints
description: >
  Profiles slow PostHog API endpoints when the main cost is in Postgres or
  Python. Use when a screen, picker, or list is slow; a Django endpoint has high
  tail latency; a query plan changes with tenant size; or a proposed database
  fix needs production evidence. Covers APM traces, safe production EXPLAIN,
  representative measurements, implementation choices, tests, rollout, and
  post-deploy verification. For ClickHouse or HogQL latency, use
  `optimizing-clickhouse-and-hogql-queries` instead.
---

# Profiling slow API endpoints

Use this skill when a PostHog API request spends most of its time in Postgres or Python.
For ClickHouse and HogQL, use
[`optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md).

Measure the same user action before and after the change.
A faster query does not help if the action stays slow.

## Find the source of the delay

Record the page action, endpoint, request shape, affected users, request volume, and a latency percentile such as p95.
Read slow APM traces with `posthog:query-apm-spans` and the `exploring-apm-traces` skill.
The distribution shows how often requests are slow.
The traces show where they spend time.

- Django ORM and `cursor.execute` spans point to Postgres.
- ClickHouse work belongs in the ClickHouse skill.
- Time outside database spans can indicate repeated calls, serialization, or excess data loading.

Follow the request to the function that creates the work.
Do not optimize a view wrapper when another function owns the delay.

## Capture the exact work

Get the SQL and parameters from a slow request.
Keep its filters, ordering, and page size.
Check for repeated queries, count queries, and work that does not block the response.
A reduced query can use a different plan.
Local data and statistics can also produce a different plan.

Use
[`querying-production-databases-via-metabase`](../querying-production-databases-via-metabase/SKILL.md)
to inspect the production read replica.
Start with `EXPLAIN`.
Use `EXPLAIN (ANALYZE, BUFFERS)` only when the exact `SELECT` is safe to run.
Inspect row estimates, indexes, join types, loops, filters, sorts, and buffer use.

## Compare the smallest useful change

Remove work that the response does not need before you change a query or add an index.
Compare the original and candidate with the same parameters.
Run each more than once, record the cache state, and verify equal results.

Measure the tenant-size distribution when plans can change with tenant size.
Test both sides of a plan crossover before you select a threshold.
One tenant is not enough evidence for a conditional plan.

Prefer one plan when it performs well across the measured range.
If a size check or cache selects the plan:

- keep the check cheaper than the work it avoids
- let stale data affect latency, not results
- keep the request working when the cache fails
- record the selected plan on the request span

Use a feature flag when behavior is uncertain or the change needs a staged rollout.
Do not use a flag as a substitute for measurements.

## Verify the change

Test public behavior at the lowest useful level.
Add plan or SQL-shape tests only when the improvement depends on that shape.
Test each plan and the failure path when the code selects between plans.
Use a representative database for plan and timing comparisons because unit tests cannot prove latency.

After deployment, check the same latency measure, request volume, error rate, and database load.
Compare recorded plan attributes when more than one plan exists.
Remove the change if it does not improve the user action without a regression.

## Common mistakes

- Starting with a code theory instead of a slow trace.
- Measuring only the mean or one warm query.
- Testing SQL that differs from the endpoint SQL.
- Selecting a threshold from one tenant.
- Moving the first response behind optional work.
- Adding an index before checking the current plan.
- Declaring success from tests instead of the production measure.
