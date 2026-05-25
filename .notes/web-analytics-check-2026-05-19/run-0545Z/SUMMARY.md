# Web analytics snapshot — 2026-05-19 05:45 UTC (run-0545Z)

Diff vs run-0513Z. Last 6h window, prod-us ONLINE.

## Watch list resolved

### 1. `external_clicks_query` p95 elevation: single-team artifact

`q13_ext_clicks_by_team.tsv` makes this clean. Of 71 queries in 6h:

| team_id   | access_method     | cnt | avg ms | p95 ms | max ms |
| --------- | ----------------- | --- | ------ | ------ | ------ |
| **125691**| personal_api_key  | 54  | 1241   | 4448   | 7748   |
| 273906    | "" (UI)           | 5   | 478    | 509    | 515    |
| 103946    | "" (UI)           | 3   | 464    | 489    | 490    |
| 208866    | "" (UI)           | 3   | 476    | 491    | 491    |
| 5 others  | mixed             | 1–2 ea | 500–1400 |  |  |

**76% of the volume and ~all the latency come from one team's personal API
key** (team 125691, api_key_label "search app" — same heavy poller as the
external clicks samples in prior runs). UI traffic for this tag is sub-600ms.

The aggregate p95 of 3.6s is misleading as a user-facing metric. Filter on
`access_method=''` to get the real UI number for any external clicks
comparison.

### 2. `stats_table_path_bounce_query` slow tail: 6 queries >10s, 6 different teams

`q14_pathbounce_outliers.tsv`:

| team_id | duration | read_rows | memory  | event_time           |
| ------- | -------- | --------- | ------- | -------------------- |
| 245952  | 26.2s    | 25.5M     | 1.34 GB | 2026-05-19 02:05:38  |
| 298634  | 14.5s    | 7.45M     | 1.53 GB | 2026-05-19 04:10:07  |
| 249533  | 14.0s    | 2.05M     | 1.53 GB | 2026-05-19 02:05:11  |
| 317027  | 12.9s    | 7.61M     | 1.53 GB | 2026-05-19 02:00:22  |
| 293278  | 10.4s    | 7.77M     | 1.56 GB | 2026-05-19 04:10:09  |
| 423348  | 10.1s    | 1.32M     | 1.53 GB | 2026-05-19 04:01:18  |

- 6 teams, all UI traffic. Not a single bad actor — a recurring shape.
- Two visible clusters at 02:00–02:05 and 04:01–04:10 — likely dashboard
  cohorts auto-refreshing on a shared cadence.
- Memory usage clusters tightly around 1.5 GB across very different read_rows
  counts (1.3M to 25.5M). Suggests the per-query memory floor is set by the
  query plan itself (states, intermediate aggregation buffers), not the input
  scan. Confirms the win shape: lazy precomp should both drop the read_rows
  (by reusing cached aggregate states) and shrink the memory floor.

### 3. Preaggregated tags: still zero

Still 0 across the 6h window. Not investigating the gating code this
iteration — flag for tomorrow. Reasonable suspects: feature flag off, or
fallback runs before tagging.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 6442    | 6487      | 1537    | 1558      |
| `web_overview_query`                    | 2682    | 2732      | 1717    | 1714      |
| `stats_table_path_bounce_query`         | 2006    | 2043      | 2927    | 3022      |
| `stats_table_frustration_metrics_query` | 1987    | 2018      | 1355    | 1364      |
| `web_vitals_path_breakdown_query`       | 354     | 350       | 503     | 533       |
| `web_goals_query`                       | 283     | 292       | 3382    | 3667      |
| `stats_table_query` (legacy)            | 243     | 267       | 1828    | 1782      |
| `stats_table_entry_bounce_query`        | 180     | 178       | 2370    | 2379      |
| `external_clicks_query`                 | 71      | 42        | 3634    | 5018      |

All drift, no step changes. `external_clicks_query` count keeps climbing as
the window slides forward (more legitimately-tagged queries enter) — and the
p95 came down 5018 → 3634 once more "normal" queries diluted team 125691's
heavy poller.

## Files in this run

- `q11b_all_web_tags_6h.tsv` — per-tag 6h aggregate
- `q13_ext_clicks_by_team.tsv` — proves external_clicks p95 is one team's API poll
- `q14_pathbounce_outliers.tsv` — 6 slow path_bounce queries across 6 teams

## Watch list for next iteration

1. Whether `stats_table_preaggregated*` ever fires (now ~10h zero).
2. Whether the path_bounce >10s cluster repeats around 06:00–06:10 UTC (next
   hourly tick after observed 02:00, 04:00 clusters).
