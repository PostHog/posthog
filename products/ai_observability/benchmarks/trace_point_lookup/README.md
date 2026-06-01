# Trace point-lookup benchmark: `ai_events` vs legacy `events`

Reproducible benchmark for the LLM analytics **single-trace view** query, comparing the
new dedicated `ai_events` table against the legacy path on the main `events` table. It runs
both compiled ClickHouse queries against production and reports the cost difference.

When a user opens one trace, the frontend issues a `TraceQuery` — a point lookup for a single
`trace_id`. This bundle reproduces that lookup for both table designs and measures it.

## What is measured

- **Query:** the single-trace `TraceQuery`
  (`posthog/hogql_queries/ai/trace_query_runner.py`). Migration to `ai_events` landed in
  `#51435` (2026-04-16).
- **Workload:** a _point lookup_ — `team_id` + a fixed list of `$ai_*` events + a 30-minute
  timestamp window + one `trace_id`, grouped to a single result row. This is the hot path
  behind every trace page view.
- **Metrics (from `system.query_log`):** `query_duration_ms`, `read_rows`, `read_bytes`,
  `memory_usage`, split into cold (first run) vs warm (subsequent runs).

## The two queries (both are real compiled production SQL)

- **New (`ai_events`):** filters and groups on the native `trace_id` column — it's the 2nd
  column in `ORDER BY (team_id, trace_id, timestamp)` and also has a `bloom_filter(0.001)`
  skip index — and reads every field as a typed column.
- **Legacy (`events`):** the actual production-compiled query, captured from the prod query
  debugger (`sql/trace_query_legacy.sql.tmpl`). By the time it was retired this was **not** a
  naive JSON scan — it filtered/grouped on the materialized **`mat_$ai_trace_id`** column
  (`bloom_filter(0.001)` indexed), read numeric fields from the **`properties_group_ai`** map
  column, and pulled only the heavy blobs (`input`/`output`/`output_choices`/states/`tools`)
  via `JSONExtractRaw(properties, …)` for the matched rows.

So **both paths index `trace_id`** and both read comparable amounts of data. The new table
wins by storing everything as native typed columns clustered by `trace_id`, without the
materialized-column / property-group machinery bolted onto the giant `events` table.

> **History note.** `mat_$ai_trace_id` was added 2025-09-19 (migration 0147). Before that, the
> legacy query `JSONExtract`-ed the `properties` blob and was far slower (multi-GB scans, over
> a second). This benchmark reproduces the **final** pre-migration state (the optimized one) —
> the fair "what we actually replaced". If you want the pre-2025-09 cost, that's a different,
> larger number.

## The 30-minute window

Reproduced from production. Opening a trace navigates with `timestamp = trace.createdAt − 5min`
(`getTraceTimestamp`); the frontend sets `date_to = date_from + 10min`; the backend
`TraceQueryDateRange` pads `±CAPTURE_RANGE_MINUTES (10)`. Net: a **30-minute window centered on
the trace's first timestamp**, `[createdAt − 15min, createdAt + 15min]`. Both queries use the
identical window, so the comparison is apples-to-apples.

## Sampling

- **Random traces, not size buckets** — to avoid bias. The script picks `N` distinct traces
  uniformly (ordered by `cityHash64(trace_id)`, so the selection is reproducible) from a scope,
  over a **±1-day window** `[DATE − 1d, DATE + 1d]` to average out single-day / time-of-day
  effects.
- **Scope** (`SCOPE`): `all` (random across every team) or a single `<team_id>` (e.g. one
  heavy user). Run both to compare a representative cross-team sample against a specific team.
- `DATE` must sit **inside the dual-write overlap** (when AI events were written to both
  `events` and `ai_events`) so each trace exists in both tables. Both tables have ~30-day
  retention, so old dates age out.

## Prerequisites

- `hogli` available (PostHog repo tooling) and a Metabase SSO session for the region:

  ```bash
  hogli metabase:login --region us
  ```

  Metabase sits behind SSO, so this must be done interactively once per region.

## Run it

```bash
cd products/ai_observability/benchmarks/trace_point_lookup
hogli metabase:login --region us

# random traces across all teams
SCOPE=all DATE=2026-05-18 N=30 RUNS=3 ./run_benchmark.sh

# random traces from one team
SCOPE=<team_id> DATE=2026-05-18 N=30 RUNS=3 ./run_benchmark.sh
```

Overridable via env: `REGION` (us/eu), `SCOPE` (`all` or a numeric team id), `DATE`, `N`
(traces), `RUNS` (repeats per query), `DB_ID` (skip auto-discovery), `AGG_WINDOW_MIN`.

The script: (1) randomly selects `N` traces in the scope over `[DATE−1d, DATE+1d]`, capturing
each trace's `team_id` + first timestamp; (2) builds the new + legacy point-lookup per trace
(30-min centered window) with a unique marker comment; (3) runs each `RUNS` times; (4)
aggregates the per-run stats from `query_log` by variant.

## Reading the output

One row per table variant (`NEW` = `ai_events`, `OLD` = legacy `events`). Example from a
`SCOPE=all` run:

```text
variant samples med_dur_ms avg_dur_ms p95_dur_ms med_read_rows med_read_bytes med_peak_mem cold_med_dur_ms warm_med_dur_ms
NEW     90      92         101        141        525           6.18 MiB       4.42 MiB     92              92
OLD     89      363        399        641        1782          6.11 MiB       24.00 MiB    368             357
```

`NEW` wins ~4× on latency and ~5× on memory; bytes read are comparable for a cross-team
sample because both index `trace_id`. For a single high-volume team the gap is larger
(denser windows make the legacy scan touch more rows), e.g. ~6× latency and ~3× bytes/memory.

## Running the queries by hand (no script)

Everything is plain ClickHouse SQL, runnable in the Metabase UI against the ClickHouse PROD
ONLINE database, or via `hogli metabase:query --region us --database-id <id> --file <file>`:

1. `sql/select_random.sql.tmpl` — random traces for a scope/window (gives `team_id`,
   `trace_id`, `first_ts`).
2. `sql/trace_query_new.sql.tmpl` / `sql/trace_query_legacy.sql.tmpl` — the two point lookups.
   Fill the `@@…@@` placeholders: `@@TEAM@@`, `@@TRACE@@`, and the window `@@DFROM@@`/`@@DTO@@`
   = `first_ts ∓ 15min` (UTC). The leading `/* … */` marker lets you find the run in
   `query_log`.
3. `sql/aggregate.sql.tmpl` — read the per-run stats back out of `system.query_log`.

## Caveats

- **Legacy query is the verbatim prod-compiled SQL** (captured from the prod query debugger):
  materialized `mat_$ai_trace_id` filter + `properties_group_ai` for numerics + `JSONExtractRaw`
  for the heavy blobs. It is **not** a hand-approximation and **not** a naive JSON scan — by the
  end the old path was already index-optimized, which is why the gap is ~4× and not orders of
  magnitude. (Pre-2025-09-19 it _was_ a JSON scan; see the history note.)
- **Warm production cluster.** Page cache can't be flushed without admin, so these are
  warm-cluster numbers (realistic for prod; cold ≈ warm here).
- **Random-by-trace sampling** counts each distinct trace once. An `all`-teams run is therefore
  dominated by high-volume teams (they have more traces) — which mirrors real query load.
- **Distributed `read_rows`/`read_bytes`** are taken from the initiating query's `query_log` row.
- A trace may fail if `mat_$ai_trace_id` / `properties_group_ai` aren't populated for it; the
  script prints a `failures:` count and `query_log` only aggregates successful runs.
