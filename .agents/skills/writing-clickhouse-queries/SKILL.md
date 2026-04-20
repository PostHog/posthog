---
name: writing-clickhouse-queries
description: Guide for writing performant ClickHouse queries in PostHog product code. Use when implementing a query runner extending QueryRunner, writing HogQL in backend Python under posthog/hogql_queries/ or posthog/hogql/, designing ClickHouse tables for a new product, choosing row ID formats (UUIDv7 vs UUID), adding materialized columns or skip indexes (minmax, bloom_filter, ngrambf_v1), testing that skip indexes are used, or debugging slow ClickHouse queries (EXPLAIN PLAN, trace logging, system.query_log). Covers HogQL vs raw SQL, QueryRunner patterns, UUID storage as UInt128, demo data generation, and the performance debugging workflow.
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
