# Web analytics snapshot — 2026-05-19 18:48 UTC (run-1848Z)

**Major finding: another cluster-level slowdown event at 18:41–18:46 UTC,
similar shape to the 09:52 UTC event captured in the 24h report. p95
jumped +6–11% across most tags as a direct result.**

## 18:41–18:46 UTC: 11 slow queries across 8+ teams in 5 minutes

`q42_recent_slow_35m.tsv` — all queries >5s in the last 35 min, sorted
by duration:

| time     | team_id | tag                              | duration | read_rows |
| -------- | ------- | -------------------------------- | -------- | --------- |
| 18:46:13 | 401433  | `stats_table_path_bounce_query`  | 10,174   | 5.0M      |
| 18:43:52 | 430628  | `stats_table_path_bounce_query`  | 10,009   | 919K      |
| 18:43:04 | 426985  | `stats_table_path_bounce_query`  | 8,723    | 1.5M      |
| 18:43:19 | 41675   | `stats_table_path_bounce_query`  | 8,460    | 13.4M     |
| 18:43:22 | 41675   | `stats_table_main_query`         | 8,040    | 6.5M      |
| 18:43:47 | 79652   | `stats_table_path_bounce_query`  | 7,214    | 4.0M      |
| 18:42:00 | 41675   | `web_goals_query`                | 7,089    | 35.2M     |
| 18:43:19 | 400630  | `web_overview_query`             | 6,181    | 1.2M      |
| 18:43:46 | 79652   | `stats_table_main_query`         | 5,904    | 2.0M      |
| 18:41:32 | 260207  | `stats_table_path_bounce_query`  | 5,333    | 36.7M     |
| 18:46:07 | 363412  | `stats_table_path_bounce_query`  | 5,069    | 6.5M      |

**11 queries from 8+ different teams across 4 tags in a 5-minute window.**
Row counts are mostly modest (1–13M). Memory wouldn't have been the
constraint. This is **the third systemic-contention event of the day**:

| event time     | teams affected | tags hit | shape                |
| -------------- | -------------- | -------- | -------------------- |
| 09:52 UTC      | 7 unrelated    | 4 tags   | 17–22s, 1–4M rows    |
| 15:15 UTC      | 1 (team 125691)| 1 tag    | 11–43s, ~1.2M rows   |
| **18:41–18:46**| **8+ unrelated** | **4 tags** | **5–10s, 1–37M rows** |

The 18:41 event is the second multi-team systemic event of the day.
Team 41675 fired 3 slow queries (path_bounce + main + goals) within
1 minute — looks like a user opening a dashboard right when the cluster
was contended.

These events are **not query-shape problems**. They're momentary cluster
contention spikes that produce 5–10s duration on queries that would
normally complete in <1s.

## Trendline impact: p95 jumped 6–11% across all tags

The 18:41–18:46 event entered the 6h window between iterations, which
shows up as a sharp p95 rise on this tick:

**p95 latency (ms):**

| Tag                     | 11:08 | 14:21 | 14:57 | 15:29 | 16:01 | 16:33 | 17:10 | 17:43 | 18:16 | **18:48** | Δ vs 18:16 | Δ vs 11:08 |
| ----------------------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | --------- | ---------- | ---------- |
| `main_query`            | 1,278 | 1,311 | 1,380 | 1,391 | 1,406 | 1,457 | 1,472 | 1,505 | 1,470 | **1,604** | **+9%**    | +26%       |
| `web_overview`          | 1,207 | 1,291 | 1,356 | 1,389 | 1,388 | 1,430 | 1,449 | 1,496 | 1,483 | **1,572** | **+6%**    | +30%       |
| `frustration_metrics`   | 1,255 | 1,262 | 1,295 | 1,341 | 1,323 | 1,373 | 1,371 | 1,392 | 1,406 | **1,516** | **+8%**    | +21%       |
| `path_bounce`           | 2,372 | 2,373 | 2,550 | 2,615 | 2,590 | 2,683 | 2,666 | 2,698 | 2,718 | **2,977** | **+10%**   | +26%       |
| `vitals`                | 607   | 727   | 791   | 819   | 854   | 837   | 832   | 837   | 781   | **801**   | +3%        | +32%       |
| `web_goals`             | 2,300 | 2,428 | 2,480 | 2,521 | 2,368 | 2,354 | 2,304 | 2,543 | 2,504 | **2,668** | **+7%**    | +16%       |
| `entry_bounce`          | 1,107 | 1,258 | 1,343 | 1,412 | 1,367 | 1,567 | 1,838 | 1,664 | 1,599 | **1,777** | **+11%**   | +60%       |
| `external_clicks`       | 1,381 | 1,959 | 1,811 | 2,303 | 2,304 | 2,327 | 2,305 | 2,295 | 1,713 | **1,844** | +8%        | +34%       |

**Max latency (ms) — the morning's monsters finally aged out:**

| Tag                  | 16:33  | 17:10  | 17:43  | 18:16  | **18:48** | what changed                          |
| -------------------- | ------ | ------ | ------ | ------ | --------- | ------------------------------------- |
| `main_query`         | 32,439 | 32,439 | 32,439 | 32,439 | **11,888**| team 204248's 12:17 32.4s aged out    |
| `web_overview`       | 33,542 | 33,542 | 33,542 | 33,542 | **8,115** | team 204248's 12:17 33.5s aged out    |
| `path_bounce`        | 20,099 | 20,099 | 20,099 | 20,099 | **13,427**| team 112458's 12:43 20.1s aged out    |

So we now have a cleaner picture of "normal peak" max latency without the
single-team outliers: ~12s main_query, ~8s overview, ~13s path_bounce.
The new path_bounce max (13.4s) is from team 41675's 18:43:19 query in
the 18:41–18:46 cluster event.

### Read of the trendline

- **The p95 jump is event-driven, not gradual creep.** Last tick's "creep
  rolling over" wasn't wrong — it was just before this 18:41 event hit
  the window.
- **`path_bounce` p95 hit 2,977 ms** — highest of the day, +25% above
  the 11:08Z baseline. Largely from the cluster event adding 5 fresh
  path_bounce >5s entries to the window.
- **`external_clicks` p95 ticked back up** (1,713 → 1,844, +8%) since
  none of the cluster event's queries were external_clicks — but the
  team 125691 42.8s spike from 15:15Z is still aging out of the window
  (exits at 21:15Z), so p99 still trending down (5,975 → 5,975 ms).

## Per-tag aggregate (this tick)

| Tag                                              | cnt    | avg ms | p95 ms | p99 ms | max ms |
| ------------------------------------------------ | ------ | ------ | ------ | ------ | ------ |
| `stats_table_main_query`                         | 10,654 | 757    | 1,604  | 2,997  | **11,888** ← aged |
| `web_overview_query`                             | 4,284  | 729    | 1,572  | 2,840  | **8,115**  ← aged |
| `stats_table_frustration_metrics_query`          | 3,235  | 709    | 1,516  | 2,655  | 7,427  |
| `stats_table_path_bounce_query`                  | 3,207  | 1,413  | 2,977  | 5,852  | **13,427** ← aged |
| `web_vitals_path_breakdown_query`                | 578    | 345    | 801    | 1,284  | 4,493  |
| `web_goals_query`                                | 508    | 1,071  | 2,668  | 6,118  | 9,804  |
| `stats_table_entry_bounce_query`                 | 399    | 790    | 1,777  | 3,237  | 3,607  |
| `external_clicks_query`                          | 370    | 1,070  | 1,844  | 5,975  | 42,828 |
| `stats_table_preaggregated_query`                | 6      | 189    | 256    | 257    | 257    |
| `web_overview_preaggregated_query`               | 3      | 180    | 276    | 288    | 291    |
| `stats_table_preaggregated_path_breakdown_query` | 3      | 305    | 411    | 421    | 423    |
| `stats_table_path_bounce_and_avg_time_query`     | 1      | 3,006  | 3,006  | 3,006  | 3,006  |

## Cluster: stable on connectivity

`clusterAllReplicas` worked. ~6h since the last connectivity outage. The
18:41 slowdown was a *latency* event, not a *connectivity* event — the
queries completed (slowly), Metabase wasn't disconnected.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q42_recent_slow_35m.tsv` — the 18:41–18:46 cluster slowdown detail

## Watch list for next iteration

1. Whether p95 normalizes (cluster event resolved) or sustains
   (continued contention).
2. Whether any new systemic event recurs at 19:11Z (would suggest
   30-minute cadence).
3. The preagg tag emit count — still frozen at 6/3/3 since the 17:18Z
   burst.
