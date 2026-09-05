# Measuring fan-out payoff across the fleet

Step 0 of `converting-fanout-parents-to-warehouse` needs production numbers.
This is where they live and how to get them without the traps.

## Access

The numbers come from the Postgres mirror tables in PostHog's own US project (project 2), queried through HogQL.
Reach them however this session can:

- the PostHog MCP server, if one is connected — `execute-sql` against project 2
- otherwise a read-only personal API key with query access to project 2, via the query endpoint

If neither is available, say so and stop rather than substituting guesses.
A conversion decision built on assumed volumes is worse than no decision, because it looks measured.

## Tables

- `postgres_posthog_externaldataschema` — one row per schema: `id`, `team_id`, `source_id`, `name`, `should_sync`, `sync_type`, `status`, `latest_error`
- `postgres_posthog_externaldatasource` — `id`, `source_type` (the vendor, e.g. `Sentry`)
- `postgres_posthog_externaldatajob` — one row per run: `schema_id`, `team_id`, `created_at`, `updated_at`, `rows_synced`, `status`
- `postgres_posthog_datawarehousetable` — `row_count`, the **full** table size

EU has its own mirrors (`eu_postgres_posthog_*`) and lacks some tables; US alone is enough for a payoff decision.

## Which row count

Use `postgres_posthog_datawarehousetable.row_count` for the parent's size.

A job's `rows_synced` is what that run wrote. On an incremental parent that is the changed-rows delta, while the fan-out re-fetches the entire listing every run — so `rows_synced` understates the listing by orders of magnitude on exactly the parents worth converting.
Use `rows_synced` only for the child's regression guard in step 4, where run-over-run comparison is the point.

## Traps

- **Results truncate at about 100 rows, silently.** Aggregate, or collapse a list into one cell with `arrayStringConcat(groupUniqArray(x), ',')`. A list that ends suspiciously round was cut.
- **Filter by `source_type` in every query.** Schema names collide across sources: `documents`, `coupons`, `submissions` and `subscribers` all exist as user table names in SQL sources, and will pollute a fan-out ranking with unrelated volume.
- **`team_id` is a reserved word in HogQL** and cannot be used as a column alias. Alias it to something else (`tid`).
- **The obvious three-way join times out.** Pre-filter instead: resolve the source ids in a subquery (`WHERE source_id IN (SELECT id FROM ... WHERE source_type = '...')`), then join the job rows.
- **Mirror replication lags**, typically minutes but sometimes hours. Check `max(created_at)` before treating a window as complete, and prefer Loki for anything in the last hour.

## Endpoint config, not the database

Page size is not in the mirrors.
Read it from the source's endpoint config in `products/warehouse_sources/backend/temporal/data_imports/sources/<source>/settings.py`: the per-endpoint `page_size`, or `page_size_param=None` for endpoints that return the collection unpaginated.
Requests, not rows, are what step 0 decides on.
