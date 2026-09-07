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

The goal is a smaller user-visible delay, not a faster query in isolation.
Measure the same request before and after the change.

## 1. Define the slow interaction

Identify the page action, endpoint, request shape, and affected users.
Use a latency distribution such as p95 with request volume.
The mean alone can hide slow requests.

Read one or more slow APM traces.
Use `posthog:query-apm-spans` and the `exploring-apm-traces` skill.
The trace shows which span owns the delay.
The distribution shows how often the delay occurs.

## 2. Find the layer that owns the delay

- A Django ORM or `cursor.execute` span points to Postgres.
- A query runner points to ClickHouse. Switch to the ClickHouse skill.
- Time outside database spans often points to repeated calls, serialization, or excess data loading.

Follow the request into the function that creates the work.
Do not optimize the view wrapper if another function owns the cost.

## 3. Capture the exact work

Get the SQL and parameters from the slow request.
Keep its filters, ordering, and page size.
Also check for repeated queries, count queries, and work that does not block the response.

A reduced query can produce a different plan.
A local plan can also differ because local data and statistics differ from production.

## 4. Inspect a production plan safely

Use
[`querying-production-databases-via-metabase`](../querying-production-databases-via-metabase/SKILL.md)
to query the production read replica.
Start with `EXPLAIN`.
Use `EXPLAIN (ANALYZE, BUFFERS)` only for a narrow `SELECT` that is safe to execute.

Check:

- estimated rows against actual rows
- the selected indexes and join types
- loops, rows removed by filters, and sort work
- shared buffer reads and hits
- work that grows with tenant size or result size

## 5. Test the smallest useful change

First remove work that the response does not need.
Then consider a query or predicate change.
Consider a new index only when measurements support it and write cost is acceptable.

If one plan helps small tenants but harms large tenants, measure the tenant-size distribution.
Test both sides of the crossover before you select a threshold.
Do not select a threshold from one tenant.

Compare the original and candidate with the same parameters.
Run each form more than once and record the cache state.
Verify that both forms return the same result.

## 6. Implement for safe failure

Prefer one plan for all tenants when it performs well across the measured range.
Add a conditional plan only when the measurements require it.

If a performance-only decision uses a cache or a size check:

- keep the check cheaper than the work it avoids
- accept a stale value when it only changes latency
- keep the request working when the cache fails
- record the selected path on the request span

Use a feature flag when the change has uncertain behavior or needs a staged rollout.
Do not add a flag only to hide missing measurements.

## 7. Add useful tests

Test the public behavior at the lowest useful level.
Add a plan or SQL-shape test only when the improvement depends on that shape.
If the code selects between plans, test both sides and the failure path.

A unit test cannot prove production latency.
Use a representative database to compare plans and timings.

## 8. Verify after deployment

Check the deploy time, then read the same latency measure and request volume.
Use the recorded span attribute to compare paths when the implementation has more than one.
Check error rate and database load for regressions.

Report the result as one of these:

- the user-visible latency improved without a regression
- the result is mixed and needs another change
- the change did not help and should be removed

## Common mistakes

- Starting with a code theory instead of a slow trace.
- Measuring only the mean or one warm query.
- Testing SQL that differs from the endpoint SQL.
- Selecting a threshold from one tenant.
- Moving the first response behind optional work.
- Adding an index before checking an existing plan.
- Declaring success when tests pass but the production measure does not improve.
