---
name: writing-clickhouse-queries
description: Guide for writing performant ClickHouse queries in PostHog product code. Use when writing HogQL query runners, designing a ClickHouse table for a new product, adding materialized columns or skip indexes, or choosing a row ID format. For optimizing an existing query that is already too slow, use `/optimizing-clickhouse-and-hogql-queries` instead.
---

# Writing ClickHouse queries for new products

**If you're optimizing an existing query rather than writing a new one**, this is the wrong skill. Use [`/optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md) instead. That skill covers layer triage, smell scanning (`FROM ... FINAL`, `JSONExtract` over properties, missing skip indexes, self-joins, CTE blow-up), measurement on the Test Cluster, and applying the fix at the right layer.

Read [`docs/published/handbook/engineering/databases/clickhouse-queries-new-products.md`](../../../docs/published/handbook/engineering/databases/clickhouse-queries-new-products.md) for the authoritative guide on writing new queries.

Then pull in whichever related docs the task touches:

- [`hogql-python.md`](../../../docs/published/handbook/engineering/databases/hogql-python.md) for HogQL in Python
- [`materialized-columns.md`](../../../docs/published/handbook/engineering/databases/materialized-columns.md)
- [`query-performance-optimization.md`](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md)

## When to use

- Writing or reviewing a `QueryRunner` subclass in `posthog/hogql_queries/` or `products/*/backend/`
- Adding a new ClickHouse table or ALTER for a product (`posthog/clickhouse/migrations/`)
- Choosing a row ID format for a new table
- Adding or removing materialized columns, skip indexes, or projections

For investigating an existing slow query, debugging a `system.query_log` row, or reviewing a proposed HogQL printer change for performance, use [`/optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md).

Not the right skill for: customer-facing ad-hoc HogQL via Max / `posthog:execute-sql`, use `query-examples` for that. For migration mechanics (node roles, engines, replication), use `clickhouse-migrations`.
