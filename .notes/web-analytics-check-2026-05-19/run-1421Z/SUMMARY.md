# Web analytics snapshot — 2026-05-19 14:21 UTC (run-1421Z)

Diff vs run-1349Z. Steady state. One new finding on goals.

## `web_goals_query` slow buckets are scattered, not synchronized

`q35_goals_15m_4h.tsv` — 15-min buckets, last 4h:

| Bucket  | cnt | p95 ms | p99 ms | max ms |
| ------- | --- | ------ | ------ | ------ |
| 10:15   | 5   | 2296   | 2488   | 2536   |
| 10:30   | 15  | 1876   | 1948   | 1966   |
| 10:45   | 5   | 2656   | 2932   | 3001   |
| 11:00   | 7   | 2151   | 2473   | 2554   |
| 11:15   | 5   | 808    | 838    | 845    |
| 11:30   | 16  | 867    | 869    | 869    |
| **11:45** | 9 | **4679** | **5919** | **6229** ← team 234917 |
| 12:00   | 20  | 2211   | 2280   | 2297   |
| 12:15   | 18  | 1448   | 1527   | 1547   |
| 12:30   | 26  | 1124   | 2196   | 2551   |
| **12:45** | 32 | 2424   | 4865   | **5926** |
| 13:00   | 14  | 1243   | 2071   | 2278   |
| 13:15   | 19  | 2406   | 2431   | 2437   |
| **13:30** | 9  | **5029** | **5934** | **6160** |
| 13:45   | 9   | 1642   | 1949   | 2026   |
| 14:00   | 15  | 1706   | 2180   | 2298   |
| 14:15   | 6   | 1194   | 1224   | 1231   |

Three separate slow buckets in 4h (11:45, 12:45, 13:30), each with max
~6.2s. **Not synchronized** with each other or with anything else — they
look like independent users running heavier goals queries (longer date
range, more goals defined, or wider filter combinations). Different shape
from the morning's 02:00/04:00 *coordinated* scheduled-refresh cluster.

The earlier-noted p99 jump (3878 → 5241 → 5282) is real but not concerning:
small 4–6s outliers happen and decay out of the window. No persistent
incident.

## New emit: `stats_table_path_bounce_and_avg_time_query`

This rare tag got a third event this iteration:

| time     | duration |
| -------- | -------- |
| 07:09:59 | 2280     |
| 08:31:40 | 2778     |
| **14:07:21** | **3006** |

Three events in ~7h, so an avg-time-on-page tile fires roughly 2–3 times
per shift. Always 2.3–3s. Worth noting that this rare tile's p95 sits
around the same place as the much-more-common `path_bounce_query` does
(2.4s) — modest but not particularly slow given how rare it is.

## Per-tag 6h aggregate — drift only

| Tag                                     | cnt  | p95 ms | p99 ms | max ms |
| --------------------------------------- | ---- | ------ | ------ | ------ |
| `stats_table_main_query`                | 7661 | 1311   | 2350   | 32439  |
| `web_overview_query`                    | 2945 | 1291   | 2450   | 33542  |
| `stats_table_frustration_metrics_query` | 2393 | 1262   | 2137   | 7809   |
| `stats_table_path_bounce_query`         | 2319 | 2373   | 4712   | 20099  |
| `web_vitals_path_breakdown_query`       | 571  | 727    | 1109   | 1614   |
| `web_goals_query`                       | 333  | 2428   | 5282   | 54960  |
| `stats_table_entry_bounce_query`        | 315  | 1258   | 2260   | 3380   |
| `external_clicks_query`                 | 195  | 1959   | 6674   | 10654  |
| `stats_table_path_bounce_and_avg_time_query` | 2 | 2995   | 3004   | 3006   |

All max columns unchanged from prior 2 iterations — no fresh extreme
outliers in the last hour. The four known ≥20s offenders (team 2 ×2,
team 112458, team 10085) are still the worst-case observations of the
day.

Tag counts continue rising linearly with the EU afternoon traffic.
external_clicks_query 170 → 195 (+25, consistent with team 125691's 36/hr
pacing).

## Cluster: still stable

`clusterAllReplicas` worked first try. ~1.5h since the last outage tick.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q35_goals_15m_4h.tsv` — confirms goals slow buckets are scattered

## Watch list for next iteration

1. Whether any of the three known dashboard-load teams (10085, 112458, 2)
   produce a fresh incident.
2. Cluster outage recurrence.
3. New entries in the heavy-polling Bucket 1 (still 2 teams).
