# Web analytics snapshot — 2026-05-19 16:01 UTC (run-1601Z)

Diff vs run-1529Z. Watch-list resolved: nothing systemic.

## 15:15Z spike was team 125691 alone, not systemic

`q39_1515_systemic.tsv` — all `>5s` web-analytics queries between
15:14:30 and 15:17:00 UTC. **Only 3 rows, all team 125691.**

| time     | team_id | tag                       | duration |
| -------- | ------- | ------------------------- | -------- |
| 15:15:49 | 125691  | `external_clicks_query`   | 42828    |
| 15:16:05 | 125691  | `external_clicks_query`   | 11167    |
| 15:16:29 | 125691  | `external_clicks_query`   | 18234    |

**No other teams** had slow queries during this 2.5-minute window. So
team 125691's 42.8s spike was **isolated**, unlike the 09:52 UTC event
which hit 7 unrelated teams in 21 seconds.

Possible explanations:

- Team 125691's queries went to a specific replica/shard that briefly
  slowed down.
- Their date range / filter shifted to a slower shape just for that tick
  (unlikely given the row counts are similar to their normal polls).
- A query-builder cache miss for this particular API key.

Doesn't look like a cluster-wide event. Filing under "isolated tail
spike" for team 125691's polling integration.

## 4.5s vitals outlier identified

`q40_vitals_outliers.tsv` — only result above 3.5s:

| time     | team_id | duration | read_rows | memory_mb |
| -------- | ------- | -------- | --------- | --------- |
| 15:23:46 | 72249   | 4493     | 906K      | 12        |

Single isolated query, UI traffic, modest row count and tiny memory.
Not paired with another vitals query, not part of a dashboard load.
**Probably also tail-of-contention noise**, not a query-shape problem.

Notable: occurred 7 minutes after team 125691's 15:15 spike. Could be
tail end of the same cluster-side condition, but no direct evidence
linking them.

## Per-tag 6h aggregate (vs run-1529Z)

| Tag                                     | cnt   | p95 ms | p99 ms | max ms |
| --------------------------------------- | ----- | ------ | ------ | ------ |
| `stats_table_main_query`                | 8998  | 1406   | 2454   | 32439  |
| `web_overview_query`                    | 3502  | 1388   | 2416   | 33542  |
| `stats_table_frustration_metrics_query` | 2763  | 1323   | 2193   | **5117** ← +556 |
| `stats_table_path_bounce_query`         | 2713  | 2590   | 4715   | 20099  |
| `web_vitals_path_breakdown_query`       | 588   | 854    | 1282   | 4493   |
| `web_goals_query`                       | 417   | 2368   | 6083   | 9804   |
| `stats_table_entry_bounce_query`        | 359   | 1367   | 2250   | 3380   |
| `external_clicks_query`                 | 283   | 2304   | 10746  | 42828  |
| `stats_table_path_bounce_and_avg_time_query` | 1 | 3006   | 3006   | 3006   |

- frustration max ticked up 4561 → 5117 — minor new outlier in that tag.
  Not concerning since the all-day max was 12783 hours ago.
- All other numbers drift only.

Tag counts continue increasing linearly with afternoon traffic:
+461 main_query, +142 frustration, +136 path_bounce in 32 min. Healthy
EU/US working-hour intensity.

## Cluster: stable

`clusterAllReplicas` worked first try, ~3 hours since the last outage tick.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q39_1515_systemic.tsv` — confirms 15:15 spike was single-team
- `q40_vitals_outliers.tsv` — single 4.5s vitals query identified

## Watch list for next iteration

1. Continued steady-state monitoring as EU rolls toward end-of-day
   (17:00–18:00 UTC) and US ramps further.
2. Whether team 234917 dashboards a third time.
3. Whether team 125691's polling stays in normal range after the
   15:15 anomaly.
