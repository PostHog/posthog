# Web analytics snapshot — 2026-05-19 08:59 UTC (run-0859Z)

Diff vs run-0827Z. Focus: does the user-pain `main_query` slow-tail recur?

## Headline: team 10085 had 5 slow queries in 73 seconds reading 246M rows each

`q23_main_query_slow_4h.tsv` — all `stats_table_main_query` queries >5s in
the last 4 hours. 13 rows. The most striking cluster:

| event_time | duration ms | read_rows  | memory MB |
| ---------- | ----------- | ---------- | --------- |
| 08:56:00   | 8508        | 245.8M     | 5081      |
| 08:56:10   | 7599        | 245.9M     | 4763      |
| 08:57:00   | **20067**   | 246.0M     | 5056      |
| 08:57:12   | 11053       | 245.9M     | 5057      |
| 08:57:13   | 10836       | 245.9M     | 4784      |

All team 10085, UI traffic, identical read_rows count (~246M). **Five
consecutive heavy queries in 73 seconds**, each reading 246M rows and
allocating 5 GB of memory. The 20s query is a real user staring at a
spinner for 20 seconds.

The identical read_rows count says these are the same logical query firing
repeatedly — probably a dashboard with auto-refresh, multiple tabs open, or
multiple stats_table tiles on the same dashboard issuing concurrent queries
during a single page load.

**This is exactly the workload lazy-precomp wins on.** 246M-row scan +
aggregate state is precisely what gets cached. The first query pays the
cost, the next four hit the cache. Even without lazy-precomp, basic
deduplication/in-flight-coalescing of identical concurrent queries would
turn 5 reads into 1.

Note: this is NOT a path_bounce shape — it's `main_query`. So the current
branch's lazy-precomp (only for path_bounce) wouldn't help team 10085. The
generalized version of the technique would.

## Other slow queries in the 4h window — pair pattern

| time     | team   | duration | read_rows | suspected pattern               |
| -------- | ------ | -------- | --------- | ------------------------------- |
| 08:41:29 | 119598 | 6379     | 66.3M     | single                          |
| 08:24:43 | 430628 | 7601     | 202K      | single, low row count           |
| 07:36:46 | 210253 | 5909     | 19.1M     | single                          |
| 05:36:59 | 364067 | 5155     | 1.2M      | **pair (twin queries 1ms apart)** |
| 05:36:59 | 364067 | 5161     | 1.2M      | (pair)                          |
| 05:01:42 | 412542 | 6040     | 745K      | **pair (2s apart)**             |
| 05:01:40 | 412542 | 5833     | 729K      | (pair)                          |
| 05:01:38 | 210501 | 5070     | 1.5M      | single (different team)         |

**Pair pattern**: teams 364067 and 412542 each issued two slow queries
within 1–2 seconds, with similar read_rows counts. Almost certainly two
tiles on the same dashboard hitting the same time range with slightly
different filter combos. Same root cause as team 10085, smaller scale.

**Outlier**: team 430628's 7.6s query reads only 202K rows. Slow despite
low row count — different shape. Probably a complex filter pushdown or a
join that's not scaling with row count. Worth a query_id pull if the
problem recurs.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 5865    | 6022      | 1284    | 1227      |
| `web_overview_query`                    | 2424    | 2467      | 1273    | 1232      |
| `stats_table_frustration_metrics_query` | 1871    | 1898      | 1104    | 1057      |
| `stats_table_path_bounce_query`         | 1842    | 1880      | 2228    | 2191      |
| `web_vitals_path_breakdown_query`       | 410     | 385       | 478     | 477       |
| `web_goals_query`                       | 339     | 340       | 2017    | 1794      |
| `external_clicks_query`                 | 232     | 211       | 1643    | 1816      |
| `stats_table_entry_bounce_query`        | 221     | 219       | 1529    | 1538      |
| `stats_table_query` (legacy)            | 70      | 96        | 1493    | 1476      |
| `stats_table_path_bounce_and_avg_time_query` | 2   | 1         | 2753    | 2280      |

p95 numbers ticked up slightly across `main_query` and `goals` — the
08:56–08:57 team-10085 cluster is now inside the 6h window and is the
dominant pull. Also lost some of the morning's calmest minutes off the
bottom of the window. Net: 6h aggregate is a noisy lens for short
incidents.

Legacy `stats_table_query` at 70 (from 96). Last seen still 04:15:19Z.

`stats_table_path_bounce_and_avg_time_query` has 2 events now (was 1).

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q23_main_query_slow_4h.tsv` — 13 slow main_query rows showing the
  team-10085 cluster and the pair-pattern teams

## Watch list for next iteration

1. Whether team 10085's heavy queries continue past 09:00Z (still active
   user, or one-shot dashboard load).
2. Whether the p95 step-down at 10:00Z (04:00 cluster exiting window) is
   masked by additional team-10085 activity.
3. legacy `stats_table_query` should hit zero around 10:15Z.
