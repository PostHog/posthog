# Web analytics snapshot — 2026-05-19 14:57 UTC (run-1457Z)

Drift-check after the 24h report. Steady state continues.

## New: team 234917 paired-tile dashboard on web_vitals

`q36_vitals_outliers.tsv` — last 6h vitals queries >1.5s:

| time     | team_id | duration | read_rows | memory_mb |
| -------- | ------- | -------- | --------- | --------- |
| 14:44:58 | 234917  | 3263     | 6.56M     | 7         |
| 14:44:56 | 234917  | 3133     | 6.56M     | 9         |
| 10:41:49 | 430943  | 1614     | 6K        | 3         |

Team 234917 ran two `web_vitals_path_breakdown_query` calls **2 seconds
apart**, reading nearly identical 6.56M-row counts. **Paired-tile pattern**
again — same shape as teams 10085 / 112458 / 364067 from earlier today.
Even on the vitals tag (normally p99 < 1.5s, p50 225ms), the parallel-tile
load amplifies into ~3s queries.

Memory was tiny (7–9 MB) so it's not memory pressure. This is probably
two browser tabs or two dashboard tiles concurrently issuing the same
query. Different from the heavy-scan teams — here the *query* is fine,
the *concurrency* is what slows things down.

Team 234917 already appeared earlier today: 6.2s `web_goals_query` at
11:55:56. So this team has had at least two dashboard-pattern slow
incidents in 3 hours. Candidate for the same "rapid-fire / paired tile"
optimization bucket.

## New outliers vs 24h report

Just one new outlier worth noting:

- `web_vitals_path_breakdown_query` max bumped 1614 → **3263 ms** (team
  234917 above). The vitals tag previously had the cleanest p99 of any
  tag (1.4s in 24h aggregate). Two 3s queries from one team is enough
  to move its single-tag max but doesn't change the overall picture.

No new path_bounce / main_query / overview outliers since the 24h report
generated 5 minutes ago.

## Per-tag 6h numbers (vs run-1421Z)

| Tag                                     | cnt   | p95 ms | p99 ms | max ms |
| --------------------------------------- | ----- | ------ | ------ | ------ |
| `stats_table_main_query`                | 8263  | 1380   | 2368   | 32439  |
| `web_overview_query`                    | 3142  | 1356   | 2430   | 33542  |
| `stats_table_frustration_metrics_query` | 2546  | 1295   | 2120   | **4561** ← max dropped |
| `stats_table_path_bounce_query`         | 2482  | 2550   | 4678   | 20099  |
| `web_vitals_path_breakdown_query`       | 560   | 791    | 1225   | **3263** ← new (above) |
| `web_goals_query`                       | 348   | 2480   | 6138   | 54960  |
| `stats_table_entry_bounce_query`        | 347   | 1343   | 2255   | 3380   |
| `external_clicks_query`                 | 230   | 1811   | 6522   | 10654  |
| `stats_table_path_bounce_and_avg_time_query` | 1 | 3006   | 3006   | 3006   |

`stats_table_frustration_metrics_query` max dropped 12783 → 4561 — the
old 12.8s outlier from morning aged out of the 6h window. No new fresh
outliers there. Good news.

Tag counts continue ticking up linearly. external_clicks 195 → 230 (+35,
consistent with team 125691's 36/hr cadence + a couple of other consumers).

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q36_vitals_outliers.tsv` — team 234917 paired-vitals incident

## Watch list for next iteration

1. Whether team 234917 produces a third dashboard incident (2 incidents
   in 3 hours suggests a real session).
2. Whether the path_bounce / main_query maxes continue to age out
   (32s/33s outliers were at 12:17 UTC, so they exit the window at
   18:17 UTC — still ~3h away).
3. Steady-state monitoring.
