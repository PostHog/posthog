# Web analytics snapshot — 2026-05-19 09:31 UTC (run-0931Z)

Diff vs run-0859Z. Two big findings.

## Finding 1: team 10085 is running a full dashboard heavy load

`q24_team_10085_2h.tsv` — last 2h of team 10085 activity (08:40 → 09:28
UTC). All UI traffic. Tile counts:

| Tag                                     | cnt | avg ms | p95 ms | max ms | max read_rows | max mem MB |
| --------------------------------------- | --- | ------ | ------ | ------ | ------------- | ---------- |
| `web_vitals_path_breakdown_query`       | 27  | 413    | 758    | 821    | 12.5M         | 12         |
| `stats_table_main_query`                | 16  | 5858   | 13306  | 20067  | **246M**      | **5081**   |
| `stats_table_frustration_metrics_query` | 5   | 4906   | 7569   | 7809   | **249M**      | 4428       |
| `web_overview_query`                    | 5   | 5188   | 9505   | 9997   | 246M          | 4566       |
| `web_goals_query`                       | 4   | 2527   | 3656   | 3792   | 257M          | 3605       |

**Estimate: ~135 GB total cluster memory burned in 50 minutes by one team.**
Reading 245–257M rows per tile, with each tile firing multiple times during
the window. This is one user (or one auto-refreshing dashboard) issuing the
canonical web-analytics dashboard tile set repeatedly.

The vitals tile is fine (sub-1s, only 12.5M rows). All four other tiles are
heavy — and they're heavy *together* every time the dashboard refreshes,
because each tile issues its own query.

## Finding 2: team 2 (PostHog itself) ran a 1.25-billion-row goals query

`q25_extreme_outliers.tsv` — all queries >20s in the last 6h. Four rows:

| team_id | tag                       | duration | read_rows  | memory_mb | event_time |
| ------- | ------------------------- | -------- | ---------- | --------- | ---------- |
| **2**   | `web_goals_query`         | **54960**| **1.25B**  | **26021** | 09:08:26   |
| **2**   | `web_overview_query`      | 27447    | 728M       | 16847     | 09:07:29   |
| 298634  | `stats_table_main_query`  | 21086    | 3.7M       | 721       | 04:10:21   |
| 10085   | `stats_table_main_query`  | 20067    | 246M       | 5056      | 08:57:00   |

Team 2 ("🎉 PostHog App + Website" — the project the MCP is connected to)
ran a `web_goals_query` reading **1.245 billion rows**, allocating
**26 GB memory**, for **54.96 seconds**. UI traffic. One minute earlier the
same team hit a 27s, 728M-row overview query. Either someone on the
internal team queried the public-website analytics with an absurd date
range / no filter, or it's a load test. Either way: a single dashboard load
absorbing cluster resources of this scale is worth flagging.

The `query_id`s are saved in the TSV if anyone wants to pull the original
HogQL.

## Two distinct slow-query shapes

The 4 extreme outliers reveal two patterns:

1. **Massive scans** (team 2, team 10085, ~200M–1.25B rows, multi-GB
   memory). Long date range, weak/no filter. The aggregate-cache /
   lazy-precomp pattern is the right answer.
2. **Modest row counts, bad query shape** (team 298634: only 3.7M rows,
   yet 21s). Filter pushdown or join inefficiency. Lazy-precomp doesn't
   help here — query-builder optimization does.

These need different fixes. Worth keeping the distinction in mind when
prioritizing follow-ups.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 5898    | 5865      | 1307    | 1284      |
| `web_overview_query`                    | 2485    | 2424      | 1238    | 1273      |
| `stats_table_frustration_metrics_query` | 1879    | 1871      | 1156    | 1104      |
| `stats_table_path_bounce_query`         | 1829    | 1842      | 2266    | 2228      |
| `web_vitals_path_breakdown_query`       | 389     | 410       | 548     | 478       |
| `web_goals_query`                       | 358     | 339       | 2112    | 2017      |
| `external_clicks_query`                 | 259     | 232       | 1533    | 1643      |
| `stats_table_entry_bounce_query`        | 250     | 221       | 1365    | 1529      |
| `stats_table_query` (legacy)            | 41      | 70        | 1519    | 1493      |
| `stats_table_path_bounce_and_avg_time_query` | 2   | 2         | 2753    | 2753      |

- `web_goals_query` p95 +5% — team 2's 54s query and team 10085's 4 goals
  queries are inside the window.
- `stats_table_main_query` p95 +2% — team 10085's 16 heavy queries.
- `web_vitals_path_breakdown_query` p95 +15% (478 → 548) — team 10085 made
  27 vitals queries this window. Even though they were each sub-1s, the
  volume influenced p95.
- Legacy `stats_table_query` at 41 (from 70). Last seen 04:15:19Z. Should
  hit zero around 10:15Z when the timestamp rolls out.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q24_team_10085_2h.tsv` — team 10085 dashboard load
- `q25_extreme_outliers.tsv` — all >20s queries in 6h (4 rows)

## Watch list for next iteration

1. Whether team 2 continues running heavy queries (one-shot or recurring).
2. Whether team 10085's dashboard refresh continues firing.
3. legacy `stats_table_query` should hit zero by next iteration.
