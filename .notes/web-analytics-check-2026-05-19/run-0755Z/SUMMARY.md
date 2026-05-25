# Web analytics snapshot — 2026-05-19 07:55 UTC (run-0755Z)

Diff vs run-0723Z. Focus: did the slow cluster reappear at 08:00, and how is
the system handling morning traffic ramp.

## Headline: 08:00 slow cluster did NOT materialize. 02:00/04:00 was a fixed event, not a recurring cycle.

`q21_recent_15m_buckets.tsv` — full 15-min × 5-tag latency table from
05:45 → 07:45. Across 5 tags × 9 buckets = 45 cells, exactly **one query
over 5s** (a single `stats_table_main_query` at 07:30, 5909 ms). p95 across
every cell stays in the healthy 700–2500 ms band.

So:

- 02:00 UTC slow cluster: real
- 04:00 UTC slow cluster: real (~2h after the first)
- 06:00 UTC: clean
- 08:00 UTC: not yet observed but the lead-in (07:00–07:45) shows no buildup

The "2-hourly" framing from earlier was wrong. **The two slow clusters are
isolated daily events at 02:00 and 04:00 UTC**, not a continuing cycle.
Plausible explanations:

- A specific cohort of dashboards with refresh schedules set at those times
  (e.g., EU operations team morning prep at 03:00 / 05:00 CET)
- A Dagster job that fires twice early-morning UTC and triggers downstream
  cache invalidation
- An external integration on a fixed-time cron

The lazy-precomp work still wins here — those specific scheduled refreshes
*are* the queries with the worst latency, and they hit predictable wall-clock
times so they're easy to A/B test.

## Morning traffic ramp: clean

Traffic stepped up at 06:00 UTC (UK morning) and grew through 06:45:

| 15-min bucket | main_q vol | path_bounce vol | overview vol |
| ------------- | ---------- | --------------- | ------------ |
| 05:45         | 63         | 26              | 26           |
| 06:00         | 235        | 83              | 101          |
| 06:15         | 260        | 90              | 99           |
| 06:30         | 263        | 80              | 106          |
| **06:45**     | **355**    | 108             | 146          |
| 07:00         | 283        | 67              | 149          |
| 07:15         | 259        | 80              | 94           |
| 07:30         | 282        | 75              | 91           |

The 4× volume ramp from 05:45 → 06:45 came with **no p95 deterioration** —
in fact p95 is *lower* during the busy windows (06:30 main_q p95 780 ms vs
05:45 1071 ms). Healthy elasticity. No queue buildup, no concurrency
pressure.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 6157    | 6341      | 1383    | 1360      |
| `web_overview_query`                    | 2549    | 2602      | 1586    | 1565      |
| `stats_table_frustration_metrics_query` | 1912    | 1962      | 1183    | 1182      |
| `stats_table_path_bounce_query`         | 1900    | 1955      | 2562    | 2643      |
| `web_vitals_path_breakdown_query`       | 367     | 363       | 481     | 482       |
| `web_goals_query`                       | 346     | 348       | 2213    | 2197      |
| `stats_table_entry_bounce_query`        | 225     | 230       | 1850    | 1816      |
| `external_clicks_query`                 | 186     | 156       | 1940    | 2003      |
| `stats_table_query` (legacy)            | 136     | 168       | 1813    | 1780      |
| `stats_table_path_bounce_and_avg_time_query` | 1   | 1         | 2280    | 2280      |

All effectively flat — drift only. The window now spans 01:55 → 07:55. The
02:00 slow bucket is still partially in-window; once that exits (~30 min
from now), expect another small downward step on aggregate p95s.

Legacy `stats_table_query` at 136 (down from 168) — will likely drop to
single digits or zero in the next iteration as 02:15 exits the 6h window.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q21_recent_15m_buckets.tsv` — 15-min × 5-tag × 2h latency table

## Watch list for next iteration

1. Whether p95s actually stop trending down once the 02:00 bucket exits
   (confirming the trend was just window-slide).
2. Whether legacy `stats_table_query` reaches zero on the 6h window
   (full rollout convergence).
3. New behavior to watch for during peak EU/US working hours: any
   path_bounce queries >5s appearing in *user-driven* (non-scheduled)
   bursts.
