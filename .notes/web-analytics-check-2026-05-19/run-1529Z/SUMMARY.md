# Web analytics snapshot — 2026-05-19 15:29 UTC (run-1529Z)

Two notable incidents in the last hour. EU afternoon picking up.

## Incident 1: team 234917 — canonical full dashboard load captured

`q37_234917.tsv` — last 2h of team 234917 queries >1s. **20 queries in
~34 seconds** between 14:44:33 and 14:47:03 UTC, across 5 different
web-analytics tags. This is the best example I've captured all day of
what a single dashboard page-load looks like in `system.query_log`:

| event_time   | tag                              | duration ms | read_rows |
| ------------ | -------------------------------- | ----------- | --------- |
| 14:44:33     | `stats_table_main_query`         | 1687        | 11.6M     |
| 14:44:34–40  | (10 more main_query calls)       | 1000–2200   | 11.5–11.7M each |
| 14:44:42     | `web_overview_query`             | 1238        | 11.5M     |
| 14:44:48     | **`stats_table_path_bounce_query`** | **4679**    | **23.2M** |
| 14:44:54     | **`web_goals_query`**            | **6113**    | 11.7M     |
| 14:44:56     | `web_vitals_path_breakdown_query`| 3133        | 6.6M      |
| 14:44:58     | `web_vitals_path_breakdown_query`| 3263        | 6.6M      |
| 14:44:59     | `stats_table_frustration_metrics_query` | 2452 | 7.5M      |
| 14:45:29     | `web_goals_query`                | 2294        | 1.5M      |
| 14:47:03     | `web_overview_query`             | 1406        | 11.6M     |

User experience: total time-to-paint is bound by the slowest tile (6.1s
goals). Path_bounce is the second-worst at 4.7s. Both queries are in the
exact shape the lazy-precomp work targets.

Notable shapes captured:

- **The 10–12 main_query repeats in 7 seconds** suggest breakdown
  switching or rapid filter changes — each request reads ~11.6M rows
  separately. A query-result cache (or coalescing) would obviate most
  of these.
- **Two vitals queries 2 seconds apart** — the paired-tile pattern (also
  flagged in prior iteration for this same team).
- **The path_bounce 4.7s + goals 6.1s pair** is the canonical heavy-tile
  problem on a dashboard refresh — exactly the workload the current
  branch's lazy precomp short-circuits.

This is the cleanest "ideal canary user" I've seen today: medium-size
dataset, full tile set, predictable repeat pattern, slow tiles
visible. Team 234917 + lazy-precomp + flag = clean A/B.

## Incident 2: team 125691 had a 42.8-second external_clicks query

`q38_ec_42s.tsv` — last 1h of `external_clicks_query` >5s. Three
queries from team 125691 within 40 seconds:

| time     | duration ms | read_rows | memory_mb |
| -------- | ----------- | --------- | --------- |
| 15:15:49 | **42828**   | 1.24M     | 726       |
| 15:16:05 | 11167       | 1.18M     | 707       |
| 15:16:29 | 18234       | 1.28M     | 726       |

**This is the slowest external_clicks query observed all day** —
4× worse than the previous max (10.6s). All three queries read ~1.2M
rows and used ~720 MB memory, so it's not a data-volume or memory
problem — it's contention, like the 09:52 cluster slowdown earlier.

Team 125691's normal pattern (per earlier analysis) is 3 external_clicks
queries every 5 minutes, mostly 600–1000ms. **All 3 queries in one
5-minute tick degraded simultaneously.** That points to a brief
cluster-side slow event at 15:15–15:16 UTC — possibly another systemic
contention spike like 09:52 — affecting whatever shard 125691's polls
landed on.

Worth a follow-up: pull >5s queries from other teams during
15:15:00–15:16:30 to see if other teams were also degraded.

## Per-tag 6h aggregate (vs run-1457Z)

| Tag                                     | cnt   | p95 ms | p99 ms | max ms |
| --------------------------------------- | ----- | ------ | ------ | ------ |
| `stats_table_main_query`                | 8537  | 1391   | 2337   | 32439  |
| `web_overview_query`                    | 3310  | 1389   | 2410   | 33542  |
| `stats_table_frustration_metrics_query` | 2621  | 1341   | 2196   | 4561   |
| `stats_table_path_bounce_query`         | 2577  | 2615   | 4835   | 20099  |
| `web_vitals_path_breakdown_query`       | 567   | 819    | 1247   | **4493** ← new |
| `web_goals_query`                       | 350   | 2521   | 6116   | **9804** ← max dropped |
| `stats_table_entry_bounce_query`        | 349   | 1412   | 2254   | 3380   |
| `external_clicks_query`                 | 245   | 2303   | **10941** | **42828** ← new (above) |
| `stats_table_path_bounce_and_avg_time_query` | 1 | 3006   | 3006   | 3006   |

- `external_clicks_query` p99 jumped 6522 → 10941 ms — entirely from
  team 125691's 3 slow polls just now.
- `web_goals_query` max dropped 54960 → 9804 — **team 2's morning monster
  query exited the 6h window**. Goals is now bounded by ~10s outliers
  rather than 55s. Big improvement in the visible tail.
- `web_vitals_path_breakdown_query` max 3263 → 4493 ms — small new
  outlier (not from team 234917, since their max in that tag was 3263).
  Worth a brief look next iteration.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q37_234917.tsv` — team 234917's full dashboard load timeline
- `q38_ec_42s.tsv` — the 42.8s external_clicks burst from team 125691

## Watch list for next iteration

1. Whether other teams also showed >5s queries at 15:15–15:16 UTC
   (systemic vs single-team).
2. Whether team 234917 dashboards again.
3. The new 4493ms vitals outlier — what team / shape.
