# Web analytics performance snapshot — 2026-05-19 04:05 UTC

Source: `system.query_log` on prod-us ONLINE (database 143). Raw outputs in this
folder; SQL in `/tmp/wa_q*.sql`.

## Top-line (last 6h, `is_initial_query`, `QueryFinish`)

| query_type                       | count | avg ms | p95 ms | p99 ms | max ms |
| -------------------------------- | ----- | ------ | ------ | ------ | ------ |
| `web_overview_query`             | 2864  | 696    | 1590   | 3805   | 13051  |
| `web_vitals_path_breakdown_query`| 380   | 280    | 535    | 1161   | 2389   |
| `stats_table_query`              | 323   | 900    | 1656   | 4015   | 17298  |
| `web_goals_query`                | 256   | 1153   | **3467** | **8682** | 15400  |
| `WebAnalyticsPageURLSearch`      | 69    | 206    | 382    | 476    | 525    |

- **Worst tail by far: `web_goals_query`** — p95 3.5s, p99 8.7s. ~14× the count of
  page-URL-search and ~4× its p99 latency in absolute terms. If we want a single
  optimization target across the runner family, this is it.
- `web_overview_query` is the volume driver. p95 1.6s is acceptable but the
  13s max suggests one or two heavy filter combos. Worth a follow-up slice.
- `stats_table_query` count looks suspiciously low for what it covers (323/6h).
  See breakdown finding below.

## Mis-tagged: `stats_table_query` is shared with external clicks

`q5_raw_logcomment_sample.tsv` shows the last three `stats_table_query` rows
are all `kind=WebExternalClicksTableQuery` — `posthog/hogql_queries/web_analytics/external_clicks.py:116`
hardcodes `query_type="stats_table_query"` instead of `external_clicks_query`.
That means:

- The 323 `stats_table_query` count above is contaminated with external-clicks
  traffic, so the real WebStatsTableQuery footprint is smaller still.
- `q2_stats_table_breakdown_4h.tsv` finds 221 rows with empty `breakdownBy` —
  consistent with most of that bucket being external clicks (no breakdownBy field).
- `q3_path_bounce_sources_6h.tsv` is empty for InitialPage/Page breakdowns — likely
  because the breakdownBy isn't being captured in `log_comment.query.*` reliably,
  not because nobody runs PathBounce.

**Fix:** flip `external_clicks.py` to `query_type="external_clicks_query"` so the
tag matches the runner. This is also the segmentation the skill assumes.

## Heavy poller in the sample window

Top recent `stats_table_query` rows are all `team_id=125691`, `access_method=personal_api_key`,
`api_key_label="search app"` — one team is dominating sampled output. Their queries
are short (sub-1s on `WebExternalClicksTableQuery`) so they're not the latency tail,
but they inflate any per-tag count. Segment by `access_method='browser'` for
user-facing latency.

## Errors (last 24h)

| query_type                  | error                       | cnt | teams | avg ms | p95 ms |
| --------------------------- | --------------------------- | --- | ----- | ------ | ------ |
| `stats_table_query`         | QUERY_WAS_CANCELLED (394)   | 152 | 109   | 1075   | 3721   |
| `stats_table_query`         | TOO_MANY_SIMULTANEOUS_QUERIES (202) | 24 | 21 | 480  | 861    |
| `web_overview_query`        | QUERY_WAS_CANCELLED         | 24  | 18    | 1006   | 2187   |
| `web_overview_query`        | TOO_MANY_SIMULTANEOUS_QUERIES | 13 | 13    | 545    | 746    |
| `web_goals_query`           | QUERY_WAS_CANCELLED         | 14  | 10    | 936    | 2129   |
| `stats_table_query`         | **NO_COMMON_TYPE (386)**    | 2   | 1     | 510    | 553    |
| `stats_table_query`         | **MEMORY_LIMIT_EXCEEDED (241)** | 1 | 1   | 9177   | 9177   |

- **NO_COMMON_TYPE (2 hits, 1 team)** is the actionable bug — query-builder type
  mismatch. Worth pulling the exception text for the offending `query_id` and
  fixing.
- One MEMORY_LIMIT_EXCEEDED at 9.2s — likely a runaway high-cardinality breakdown.
  Sample the query_id to identify the breakdown dimension.
- TOO_MANY_SIMULTANEOUS_QUERIES (37 total) hits 21+13 teams — capacity ceiling,
  not a per-query bug.
- QUERY_WAS_CANCELLED noise is expected (dashboard remounts, navigation).

## Implication for the lazy-precomp branch

The current branch (`posthog-code/web-analytics-bounce-lazy-precomputation`,
`adbbff02378`) adds three lazy strategies for paths-with-bounce. From this
snapshot:

- We can't currently measure PathBounce vs other stats_table strategies because
  the runner emits a single `stats_table_query` tag for everything (and shares
  it with external clicks). **Before the lazy rollout lands, split the tags**
  per the skill's tag vocabulary (`stats_table_path_bounce_query`,
  `stats_table_main_query`, etc.) — otherwise we'll have no signal for
  whether the lazy strategy is helping.
- Wire up the `breakdown_by` top-level QueryTags field. Right now neither the
  top-level nor the nested form is populated reliably.

## Suggested follow-ups (smallest first)

1. Two-line fix: `external_clicks.py:116` → `query_type="external_clicks_query"`.
2. Split the stats_table tag in `stats_table.py` along the strategy axis
   (main / path_bounce / path_bounce_and_avg_time / frustration / entry_bounce
   / preaggregated / preaggregated_path / preaggregated_entry_bounce). Mirrors
   the existing strategy classes — no logic change, just tagging.
3. Add `tag_queries(breakdown_by=...)` in `WebAnalyticsQueryRunner.calculate`
   so we can attribute latency by breakdown without reading nested JSON.
4. Pull the `NO_COMMON_TYPE` exception text for the team_id in `q4_errors_24h.tsv`
   row 7 — that's a real bug.

## Files

- `q1_tag_dist_6h.tsv` — per-tag aggregate
- `q2_stats_table_breakdown_4h.tsv` — breakdown_by inside stats_table_query
- `q3_path_bounce_sources_6h.tsv` — empty (see note above)
- `q4_errors_24h.tsv` — exception_code breakdown
- `q5_raw_logcomment_sample.tsv` — three raw rows that revealed the mis-tag
