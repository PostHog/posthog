# Web analytics snapshot — 2026-05-19 07:23 UTC (run-0723Z)

Diff vs run-0650Z. Focus: identify the team cohort behind the 02:00/04:00
slow clusters.

## Headline: slow-bucket cohort identified — 15 teams, almost none active in calm windows

`q20_slow_team_cohort.tsv` aggregates per-team queries in the 02:00 and 04:00
slow buckets vs the 06:00–06:30 calm window. UI traffic only
(`access_method=''`), across path_bounce + goals + entry_bounce. 15 teams ran
a query >5s in a slow bucket. Top 6:

| team_id  | slow cnt | over 5s | calm cnt | slow avg ms | slow p95 ms |
| -------- | -------- | ------- | -------- | ----------- | ----------- |
| 21405    | 6        | **4**   | **0**    | 4977        | 7863        |
| 298634   | 6        | 2       | 0        | 4416        | 12852       |
| 227169   | 2        | 2       | 0        | 5990        | 6445        |
| 293278   | 2        | 2       | 0        | 8409        | 10238       |
| 249533   | 7        | 1       | 0        | 2673        | 10317       |
| 245952   | 1        | 1       | 0        | 26152       | 26152       |

**13 of 15 teams have `calm_bucket_cnt = 0`** — they don't touch these tags
at 06:00/06:30 at all. They show up exclusively at 02:00 and 04:00. That's
a strong signal these are **scheduled refresh patterns**, not interactive
dashboard use. Probably dashboard auto-refresh cron, alert evaluations, or
a webhook integration hitting the query endpoint at exact wall-clock hours.

Only 2 teams (317027, 426626) appear in both slow and calm buckets — those
two have actual interactive web analytics use throughout the day.

### Lazy-precomp canary candidates

The cohort above is the natural target population for the multivariate flag
in the current branch (`adbbff02378`). For the first canary I'd pick the
high-volume + high-latency teams:

- **21405** — 4 queries >5s in 1 hour of wall-clock time (most consistent)
- **298634** — p95 12.8s in slow buckets, real outlier
- **227169** — both queries went over 5s, p95 6.4s

Why these are good test subjects:

1. They're predictable — same teams hit the same slow window every day.
2. Off-peak — no concurrent UI traffic to confound the comparison.
3. Real win shape — multi-second queries that lazy precomp can directly
   short-circuit.
4. Small enough cohort that a misbehavior wouldn't fan out widely.

The 02:00 and 04:00 windows themselves become natural A/B comparison points:
flip the flag for the canary teams, watch the next morning's slow buckets,
compare to the unmodified majority cohort.

## First sighting: `stats_table_path_bounce_and_avg_time_query`

This tag has been essentially unused across all prior iterations (1 in 6h).
This iteration we got **one fresh emit at 07:09:59 UTC**, 2280ms. Confirms
the tag is wired up; just an extremely rare tile.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 6341    | 6207      | 1360    | 1514      |
| `web_overview_query`                    | 2602    | 2542      | 1565    | 1729      |
| `stats_table_frustration_metrics_query` | 1962    | 1952      | 1182    | 1293      |
| `stats_table_path_bounce_query`         | 1955    | 1960      | 2643    | 2890      |
| `web_vitals_path_breakdown_query`       | 363     | 366       | 482     | 481       |
| `web_goals_query`                       | 348     | 320       | 2197    | 2726      |
| `stats_table_entry_bounce_query`        | 230     | 190       | 1816    | 2320      |
| `stats_table_query` (legacy)            | 168     | 191       | 1780    | 1815      |
| `external_clicks_query`                 | 156     | 127       | 2003    | 2421      |
| `stats_table_path_bounce_and_avg_time_query` | 1   | (n/a)     | 2280    | —         |

All p95 numbers dropping — **this is the 23:30/00:30 slow buckets rolling
out of the 6h window**, not a real improvement. The 6h aggregate now spans
01:23 → 07:23 which excludes the worst pre-02:00 slow buckets.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q20_slow_team_cohort.tsv` — 15-team cohort responsible for slow buckets

## Watch list for next iteration

1. Whether any of the 15 cohort teams show up in the 08:00 bucket (predicts
   a third 2-hourly tick).
2. Whether the p95 rebound starts as the morning EU/US UI traffic ramps up
   ~09:00 UTC.
3. Optional follow-up: pull the actual query JSON for one of team 21405's
   slow queries to confirm it's a path-bounce shape lazy precomp would fix.
