# Dashboard v2: one batched read for cached tiles

Step 1 of the dashboards v2 roadmap ([#138125](https://github.com/PostHog/posthog/issues/138125)).
Everything here is behind the `dashboard-v2` flag, which is aggregated by project.

## Problem

A cached tile is cheap to compute but expensive to deliver.
Each tile is its own insight request, so each one repeats authentication, a dozen or more Postgres reads, the full insight serializer, and response serialization.
The browser fetches a few tiles at a time, so a large cached board paints tile by tile.
The cache read itself is a small part of that time.

## The request

`GET /api/projects/:project_id/dashboards/:id/cached_tiles/?tile_ids=1,2,3`

- Takes up to 100 tile IDs. `filters_override` and `variables_override` work as they do on the insight endpoint.
- Returns one entry per requested ID, in request order, with a `status`:
  - `hit`: the cached result, served even when it is older than its target age, as `refresh=force_cache` does today.
  - `miss`: nothing usable is cached, or the tile errored. The client loads that tile through today's per-tile path.
  - `forbidden`: the caller can't view the tile's insight. No result is returned.
  - `not_found`: the ID isn't an insight tile on this dashboard.
- Never runs a query and rejects a `refresh` parameter, in the query string or the body. It has its own compute surface, pinned to cache-only.

## What is stored where

First PR: nothing new.
The endpoint reads today's query cache entries under today's keys, in today's format.
Old and new pods read and write the same entries, so a mixed deploy is safe.

Later in step 1:

- **Tile key at save time.** Store each tile's cache key when the tile, its insight, the dashboard filters or a team setting that feeds the key changes. A read then skips rebuilding the query and, for SQL tiles, parsing it.
- **One `MGET` per board.** With stored keys, every tile's entry comes back in one round trip.
- **Results-only entries.** Debug fields such as `hogql`, `clickhouse` and `timings` stay out of what dashboards read.
- **Own worker pool for hits,** so cache hits don't queue behind long-running queries.

## How access is checked

Cached results must never cross a permission boundary. Each check matches the per-tile insight endpoint:

1. **Project.** The usual team membership and API scope checks (`dashboard:read`, `insight:read`).
2. **Dashboard.** `get_object()` applies dashboard access control. A caller without viewer access gets a 403 and no tile data.
3. **Insight.** Insight access is loaded once for all requested tiles, per environment, before anything is read. A restricted insight returns `forbidden` and its query never runs.
4. **Restricted properties and other narrowing rules.** These are part of the cache key: `get_cache_payload` adds the caller's restricted properties, and runners add their own access variants. A user with different restrictions computes a different key and misses.

The first PR reuses `InsightSerializer.insight_result` for each tile, the same code the insight endpoint runs.
The key inputs, filter layering, variables and access snapshot therefore can't drift between the two paths.
The stored-key work must keep this property: a stored key has to include an access fingerprint, which is checked on read before an entry is served.

## Fallback on miss

A miss is not an error. The client requests that tile the way it does today, which computes on demand.
If the endpoint fails as a whole (flag off, 5xx), the client falls back to per-tile loading for every tile.

## Rollout

1. Backend endpoint, flag-gated and unused (this PR).
2. Frontend: on boards in `dashboard-v2` projects, read all visible cached tiles in one request, then fall back per tile on misses.
3. Stored tile keys and `MGET`, then results-only entries, then a separate pool for hits.

Each step is measured before and after: time to paint cached tiles, and Postgres queries per batched request, which must stay flat as the tile count grows.

## Rollback

Remove the project from `dashboard-v2`. The frontend goes back to per-tile reads and the endpoint returns 404.
The cache format and keys don't change, so there is no data to migrate back.
