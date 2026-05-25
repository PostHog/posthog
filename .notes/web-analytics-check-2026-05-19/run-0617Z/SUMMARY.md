# Web analytics snapshot — 2026-05-19 06:17 UTC (run-0617Z)

Diff vs run-0545Z. Last 6h window unless noted.

## Watch list resolved

### 1. Preagg tags: zero in 48h, and it's by design

`q16_preagg_any_48h.tsv` is empty. None of `stats_table_preaggregated*` tags
have fired in 48h of prod-us traffic.

Code-side check (`stats_table.py:_resolve_strategy`, line ~50 in
`origin/master`):

```python
if (
    self.modifiers
    and self.modifiers.useWebAnalyticsPreAggregatedTables
    and self.preaggregated_query_builder.can_use_preaggregated_tables()
    and not self.query.includeAvgTimeOnPage
    and not self.query.conversionGoal
):
```

The preagg path is gated on `modifiers.useWebAnalyticsPreAggregatedTables` —
a HogQL modifier that must be explicitly opted-in. In prod, no current code
path flips that True for user-facing dashboards. So the preagg branch is
**dead in production traffic**. Not a regression; it's the current rollout
state of the feature.

This is exactly the rollout problem the lazy-precomp commit (`adbbff02378`)
is structured to solve — it adds the per-team multivariate feature flag for
`bouncePrecomputationMode` so the modifier can be flipped on per-team. The
existing preagg modifier doesn't have that wiring.

Two follow-ups that fall out of this:

- Document this explicitly so the next person doesn't waste time looking for
  preagg latency wins in `system.query_log` and finding nothing.
- The existing Dagster preagg pipeline is still building tables nobody reads
  from. Either retire those Dagster jobs, or wire a flag-gated modifier toggle.

### 2. Path bounce slow cluster: hourly hypothesis was wrong

`q15_pathbounce_5m_timeline.tsv` covers 22:15 → 06:15. Slow buckets:

| Bucket    | over_10s | between_5_10s |
| --------- | -------- | ------------- |
| 23:30     | 1        | 1             |
| 23:35     | 0        | 2             |
| 00:55     | 0        | 3             |
| **02:00** | **1**    | **2**         |
| **02:05** | **2**    | **2**         |
| **04:00** | **1**    | **2**         |
| **04:10** | **2**    | **1**         |
| 05:50     | 0        | 2             |
| 06:00–06:15 | 0      | 0             |

The 02:00 and 04:00 clusters were real. The hypothesized 06:00 follow-up
**did not appear** — three consecutive empty 5-min buckets through 06:15.
The pattern is not strictly hourly. Possible read: a 2-hourly Dagster
refresh, OR a coincidental alignment of two timezone-driven dashboard
auto-refresh cohorts. Need a longer baseline (24h+) and team_id breakdown
on the slow queries to tell.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 6223    | 6442      | 1527    | 1537      |
| `web_overview_query`                    | 2558    | 2682      | 1731    | 1717      |
| `stats_table_path_bounce_query`         | 1962    | 2006      | 2941    | 2927      |
| `stats_table_frustration_metrics_query` | 1960    | 1987      | 1362    | 1355      |
| `web_vitals_path_breakdown_query`       | 347     | 354       | 495     | 503       |
| `web_goals_query`                       | 298     | 283       | 2907    | 3382      |
| `stats_table_query` (legacy)            | 220     | 243       | 1832    | 1828      |
| `stats_table_entry_bounce_query`        | 174     | 180       | 2329    | 2370      |
| `external_clicks_query`                 | 94      | 71        | 2701    | 3634      |

- `web_goals_query` p95 -14% (3382 → 2907). Single 6h window so noise, but
  worth a second look if it sustains — last 3 windows: 3667 → 3382 → 2907.
- `external_clicks_query` p95 -26% (3634 → 2701) as team-125691's heavy
  poller continues to get diluted by lower-latency traffic.
- Everything else is drift.

## Files in this run

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q15_pathbounce_5m_timeline.tsv` — 5-min timeline, 8h window
- `q16_preagg_any_48h.tsv` — empty (proves preagg is dead in prod)

## Watch list for next iteration

1. Whether the slow path_bounce cluster shows up at 06:00 *next* day (i.e.,
   if the pattern is truly 2-hourly, expect 22:00, 00:00, 02:00, 04:00,
   06:00; if 4-hourly, expect 06:00, 10:00; if irregular, none).
2. `web_goals_query` p95 trend — is it really improving or noise?
3. Confirm that no preagg tags fire even when modifier is opted in (lazy
   precomp branch flips it — when that ships, expect the path_bounce
   preagg tag to start firing for the canary team).
