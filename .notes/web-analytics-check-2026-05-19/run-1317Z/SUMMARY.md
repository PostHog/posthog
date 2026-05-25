# Web analytics snapshot — 2026-05-19 13:17 UTC (run-1317Z)

Diff vs run-1244Z. Two prior hypotheses **corrected** by direct evidence.

## Correction 1: team 125691 cadence is 5 minutes, not 20

`q32_125691_cadence.tsv` — last 2h of team 125691 activity. The actual
pattern is **three `external_clicks_query` calls every 5 minutes**, like:

```
12:30:07, 12:30:12, 12:30:18
12:35:05, 12:35:11, 12:35:17
12:40:07, 12:40:12, 12:40:19
... (continues uniformly through 13:15)
```

That's **36 queries per hour** from one team's personal API key polling.
Most queries are 600–1000 ms, reading 1.0–1.5M rows. The 10.7s and 8.6s
slow events at 11:45 and 12:05 weren't part of a separate 20-minute cadence
— they were individual members of the 5-min triplets that happened to hit
the tail.

So team 125691's "search app" PAK fires 36 modest queries an hour, of which
~1–2% degrade into multi-second outliers. The aggregate `external_clicks_query`
count growing across iterations (90 → 116 → 148) is mostly this team's
sustained polling becoming more visible in the sliding window, not rollout
convergence.

## Correction 2: team 204248 is polling-rate problem, not query-shape

`q33_204248_recurrence.tsv` — last 6h, team 204248's `web_overview_query`
calls. The latest 30 calls all fired between **13:03:28 and 13:06:09Z**
— 30 queries in 2m41s, all reading ~7M rows, almost all sub-1s, with
occasional 1–3.5s outliers (max 3543 ms in this set).

So team 204248's actual pattern: **~11 overview queries per minute in
sustained bursts**. That's an automated integration, not interactive UI.

The 33s and 32s outliers from run-1244Z (12:17 UTC) **aren't a slow query
shape** — they were two queries that happened to hit a 30-second tail
event under the team's normal rapid-fire burst. The median query for this
team and shape is fine (sub-1s on 7M rows).

Prior iteration's framing — "31-second queries on a million rows is a
query-shape problem, not a scan-size problem" — was misleading. The real
shape is rate-limited polling that occasionally tail-spikes. The fix is
upstream (rate-limit personal-API-key polling, or coalesce duplicate
requests within a small time window), not in the query builder.

## Reclassified slow-query catalog

Two distinct buckets, with different fixes:

### Bucket 1 — automated polling that occasionally tail-spikes

| team_id | API surface | pattern                              | typical duration | tail events |
| ------- | ----------- | ------------------------------------ | ---------------- | ----------- |
| 125691  | PAK         | 3 `external_clicks_query` / 5 min    | 600–1000 ms      | ~10s × 1–2/h |
| 204248  | PAK         | ~11 `web_overview_query` / min burst | <1 s             | ~33s, rare  |

**Fix shape**: rate limiting + request coalescing. Lazy precomp does not
help.

### Bucket 2 — heavy scans on long date ranges / multiple tiles

| team_id | tag                              | duration | read_rows | memory_gb |
| ------- | -------------------------------- | -------- | --------- | --------- |
| 2       | `web_goals_query`                | 54.9s    | **1.25B** | 26.0      |
| 112458  | `stats_table_path_bounce_query`  | 20.1s    | 651M      | **24.1**  |
| 10085   | `stats_table_main_query`         | 20.1s    | 246M      | 5.1       |
| 121302  | `stats_table_path_bounce_query`  | 12.3s    | 430M      | 5.7       |

**Fix shape**: lazy precomputation / aggregate caching. The current
branch's work is the canonical fit.

## Per-tag 6h numbers — steady state continues

| Tag                                     | cnt  | avg ms | p95 ms | p99 ms | max ms |
| --------------------------------------- | ---- | ------ | ------ | ------ | ------ |
| `stats_table_main_query`                | 6896 | 681    | 1337   | 2454   | 32439  |
| `web_overview_query`                    | 2624 | 667    | 1262   | 2420   | 33542  |
| `stats_table_frustration_metrics_query` | 2168 | 611    | 1212   | 2114   | 7809   |
| `stats_table_path_bounce_query`         | 2070 | 1205   | 2391   | 4561   | 20099  |
| `web_vitals_path_breakdown_query`       | 500  | 293    | 680    | 1108   | 1614   |
| `web_goals_query`                       | 329  | 1088   | 2357   | 3878   | 54960  |
| `stats_table_entry_bounce_query`        | 290  | 661    | 1296   | 2157   | 2620   |
| `external_clicks_query`                 | 148  | 922    | 2102   | 7626   | 10654  |
| `stats_table_path_bounce_and_avg_time_query` | 1 | 2778   | 2778   | 2778   | 2778   |

Counts continue ticking up as morning ramps. p95s stable across all tags.
No new extreme outliers since 1244Z's three incidents. The earlier 09:08
team-2 monster (54.96s, 1.25B rows) is still the worst single query in
the 6h window.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q32_125691_cadence.tsv` — proves the 5-min cadence
- `q33_204248_recurrence.tsv` — proves the rapid-fire pattern

## Watch list for next iteration

1. Whether the cluster connection stays stable through the next 30 min.
2. Whether team 112458 / team 10085 dashboard refreshes recur.
3. Whether any new teams appear in the "automated polling" Bucket 1
   (a 3rd PAK consumer with similar shape would suggest a common
   integration pattern worth investigating broadly).
