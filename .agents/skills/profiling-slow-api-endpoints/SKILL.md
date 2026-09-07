---
name: profiling-slow-api-endpoints
description: >
  Turns "this screen feels slow" into a measured, landed fix for a PostHog
  endpoint whose time sits in Postgres or in Python. Covers reading an APM
  trace to find the span that holds the p95, capturing the real production
  query plan with `EXPLAIN` on the read replica, sizing the deciding dimension
  across the whole fleet before choosing a threshold, making a plan choice
  cheap, fail-open and observable, and verifying against a real database on a
  devbox. Use when an endpoint, picker, list, or scene is slow, when p95
  latency is high, when a query plan differs between local and production,
  when deciding whether an index helps or hurts, or when a latency fix must
  not regress the largest projects. For ClickHouse or HogQL query latency use
  `optimizing-clickhouse-and-hogql-queries` instead.
---

# Profiling a slow API endpoint

This is the loop from "a person says the app feels slow" to a fix that is
measured, safe for every project size, and visible in production afterwards.
It is for time spent in Postgres or in Python. For ClickHouse and HogQL, use
[`optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md).

The order matters. Most latency work goes wrong at step 1 or step 3, not at
the fix.

## 1. Get the evidence before you form a theory

Do not start from the code. Start from a request that was actually slow.

- **APM trace.** Open a trace of the slow interaction and find the span that
  holds the time. The PostHog MCP `query-apm-spans` tool reads spans, and the
  `exploring-apm-traces` skill covers trace navigation. One trace tells you
  where the time is; the p95 over a window tells you whether it matters.
- **Read p95, never the mean.** A mean hides the shape. An endpoint with a
  200 ms mean and a 13 s p95 is a broken endpoint, and the mean will tell you
  it is fine.
- **pganalyze and RDS Performance Insights** are the other entry point when
  you have no trace but you know the database is unhappy. See
  [query-performance-optimization](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md).

Write down the number you started from. Without it you cannot claim a fix.

## 2. Decide which engine holds the time

Read the span tree, not the file tree. Time in a Django ORM span or a raw
`cursor.execute` is Postgres; continue here. Time in a query runner is
ClickHouse; switch skills. Time in neither is Python, and the fix is usually
a call that repeats per row or a serializer that loads more than it returns.

## 3. Capture the plan production actually gets

**A local `EXPLAIN` proves nothing.** The planner chooses from production
statistics. The same SQL takes a different plan against a table with millions
of rows spread over thousands of projects, and that difference is normally the
whole bug.

Use `EXPLAIN (ANALYZE, BUFFERS)` against the production read replica through
[`querying-production-databases-via-metabase`](../querying-production-databases-via-metabase/SKILL.md),
which carries the auth path, the safety rules, and how to read the output.

Establish two things there: which index the planner reaches for, and whether a
predicate rewrite changes what it can reach. The rewrite is the usual lever,
because it costs no migration.

Profile the SQL the endpoint really sends, with its ordering and page size.
A simplified query takes a different plan.

## 4. Size the deciding dimension across the fleet

If your fix depends on a number, measure how that number is distributed before
you pick a threshold. This is the step people skip, and it is the one that
turns a latency win into an incident.

A rewrite that wins for the median project can lose badly for the largest, and
the largest projects are the ones that notice. Query both ends: the biggest
projects, and the percentile where most projects actually sit. Set the
threshold from the crossover you measured, then leave headroom on the side
where being wrong is expensive. The
[Metabase skill](../querying-production-databases-via-metabase/SKILL.md) has
the query.

## 5. Make the choice cheap, fail-open, and reversible

When the fix is conditional, the condition must not become the new cost or the
new outage:

- **Bound the measurement.** Count with a `LIMIT` so the check stays cheap on
  the projects it is protecting.
- **Cache it, and treat a stale answer as acceptable.** A wrong plan costs
  query time. It must never change results.
- **Fail open.** Use the safe cache helpers. A Redis outage should cost one
  extra query per request, not a 5xx.
- **Prefer a threshold you can move over a flag you must clean up**, unless
  you genuinely need a staged rollout.

## 6. Make the choice observable

Record which path a request took as a span attribute. Then the effect is
visible per request in APM, and the next person does not have to re-derive
your reasoning from the code:

```python
trace.get_current_span().set_attribute("taxonomy_search_plan", plan)
```

## 7. Verify against a real database

Unit tests on SQL strings catch a refactor that drops a wildcard. They cannot
catch a plan regression. Run the database-backed API tests on a devbox, where
a real Postgres is available, using
[`setting-up-devbox`](../setting-up-devbox/SKILL.md).

Put the before and after in the PR as a table: the query, the plan the planner
picked, and the timing, with the cache state stated. See
[`writing-pr-descriptions`](../writing-pr-descriptions/SKILL.md).

## 8. Confirm after it ships

Wait for the deploy (`checking-deploy-timing`), then read the same p95 you
started from. A latency fix is not done when CI passes; it is done when the
number moved. If the endpoint has a user-visible behavior change, see
[`announcing-behavior-changes`](../announcing-behavior-changes/SKILL.md).

## Traps

- **Adding an index is not the default fix.** A global index on a searched
  column can be the cause, because the planner cannot scope it to one tenant.
- **Do not move first paint behind a second request.** When a secondary call
  only decorates the result, let the result render without it. This is a
  latency fix that needs no database work at all.

## Worked example

The taxonomic filter search went from seconds to tens of milliseconds through
exactly this loop, including the fleet-sizing step that kept the largest
projects on the old plan. See
[references/worked-example-taxonomy-search.md](references/worked-example-taxonomy-search.md).
