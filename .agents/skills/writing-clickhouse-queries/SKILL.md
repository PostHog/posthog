---
name: writing-clickhouse-queries
description: Guide for writing performant ClickHouse queries in PostHog product code. Use when writing HogQL query runners, designing ClickHouse tables for a new product, adding materialized columns or skip indexes, or debugging slow ClickHouse queries.
---

# Writing ClickHouse queries for new products

Read [`docs/published/handbook/engineering/databases/clickhouse-queries-new-products.md`](../../../docs/published/handbook/engineering/databases/clickhouse-queries-new-products.md) for the authoritative guide.

Then pull in whichever related docs the task touches:

- [`hogql-python.md`](../../../docs/published/handbook/engineering/databases/hogql-python.md) — HogQL in Python
- [`materialized-columns.md`](../../../docs/published/handbook/engineering/databases/materialized-columns.md)
- [`query-performance-optimization.md`](../../../docs/published/handbook/engineering/databases/query-performance-optimization.md)

## When to use

- Writing or reviewing a `QueryRunner` subclass in `posthog/hogql_queries/` or `products/*/backend/`
- Adding a new ClickHouse table or ALTER for a product (`posthog/clickhouse/migrations/`)
- Choosing a row ID format for a new table
- Adding or removing materialized columns, skip indexes, or projections
- Investigating a slow ClickHouse query

Not the right skill for: customer-facing ad-hoc HogQL via Max / `posthog:execute-sql` — use `query-examples` for that. For migration mechanics (node roles, engines, replication), use `clickhouse-migrations`.
