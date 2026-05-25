# Web analytics performance — 24h report, 2026-05-19 14:52 UTC

Window: 2026-05-18 14:52 UTC → 2026-05-19 14:52 UTC.
Source: `clusterAllReplicas(posthog, system, query_log)` on prod-us ONLINE.
Filter: `is_initial_query`, `type = 'QueryFinish'`, tags matching
`stats_table*`, `web_*`, or `external_clicks_query`.

## TL;DR

- **~68,500 web-analytics queries executed across the 24h window** —
  scanning ~213 billion rows total and burning ~55 TB of cluster memory.
- **Latency is dominated by a small number of outlier shapes.** p50 across
  every tag is 200–950ms, but max values reach 32–55 seconds. Median user
  experience is fine; the tail is where the work is.
- **Three distinct slow-query shapes** identified, each needing a different
  fix:
  1. Massive-scan dashboards on long date ranges (multi-tile, often
     concurrent) — **the canonical lazy-precomp target**, and this is
     where the current branch's path-bounce work pays off.
  2. Personal-API-key polling integrations that occasionally tail-spike
     into 8–33s queries — **rate-limit / coalesce** fix, lazy precomp
     does not help.
  3. Concurrent cluster-level slow-down events that hit many unrelated
     teams within seconds of each other — **infrastructure**, not query
     shape.
- **Per-strategy tag rollout (the prior branch) fully converged at
  04:09:51 UTC** today. No legacy `stats_table_query` emits after that.
- **Active Metabase ↔ ClickHouse connectivity issue** today: ~2h
  cumulative blind time across 3 flapping windows (~10:00–10:55,
  11:40–12:44, plus shorter ticks). Cluster connection currently stable.
- **Healthy: errors are negligible.** 269 `QUERY_WAS_CANCELLED`
  (benign navigation), 3 `TIMEOUT_EXCEEDED`, 1 `MEMORY_LIMIT_EXCEEDED`,
  1 `NO_COMMON_TYPE` bug. No `TOO_MANY_SIMULTANEOUS_QUERIES` in this
  window (had 39 in the morning 24h slice — likely capacity is sized OK
  now).
- **One `web_overview_preaggregated_query` emit detected** (263ms) — the
  *first* preaggregated tag emission observed, breaking the "preagg path
  is dead in prod" finding from earlier today (was specific to stats_table
  preagg).

## 1. Per-tag picture

`r1_tags_24h.tsv`. Sorted by count.

| Tag                                              | cnt    | p50  | p95  | p99  | max ms | total mem GB | total rows (billion) |
| ------------------------------------------------ | ------ | ---- | ---- | ---- | ------ | ------------ | -------------------- |
| `stats_table_main_query`                         | 21,191 | 538  | 1329 | 2811 | 32,439 | 15,123       | 54.9                 |
| `stats_table_query` (legacy)                     | 17,902 | 589  | 1643 | 3490 | **44,174** | 15,161   | 59.4                 |
| `web_overview_query`                             | 11,914 | 497  | 1323 | 2843 | 33,542 | 8,545        | 33.4                 |
| `stats_table_frustration_metrics_query`          | 6,578  | 494  | 1233 | 2584 | 12,783 | 4,691        | 16.3                 |
| `stats_table_path_bounce_query`                  | 6,498  | 957  | 2532 | 5224 | 28,770 | 9,320        | 31.7                 |
| `web_vitals_path_breakdown_query`                | 1,754  | 225  | 726  | 1378 | 4,312  | 16           | 1.8                  |
| `web_goals_query`                                | 1,519  | 674  | 2423 | 5961 | **54,960** | 1,199    | 12.0                 |
| `stats_table_entry_bounce_query`                 | 772    | 521  | 1615 | 2766 | 7,467  | 551          | 2.5                  |
| `external_clicks_query`                          | 290    | 636  | 1704 | 6459 | 10,654 | 202          | 0.6                  |
| `stats_table_path_bounce_and_avg_time_query`     | 5      | 3309 | 4076 | 4142 | 4,159  | 9            | 0.1                  |
| **`web_overview_preaggregated_query`**           | **1**  | 263  | 263  | 263  | 263    | 0.2          | 0.0                  |

Observations:

- **`stats_table_path_bounce_query` is the slowest mainstream tag**
  (p95 2.5s, p99 5.2s). This is what the current lazy-precomp branch
  targets. It also has the second-highest total memory burn (9.3 TB) and
  the third-highest total scan size (31.7B rows) — so optimizing it has
  meaningful impact on cluster pressure, not just user-visible latency.
- **Per-query cost ranking**: path_bounce burns ~1.43 GB/query average,
  vs main_query ~0.71 GB. Path bounce is roughly 2× as expensive per
  query as main_query.
- **Legacy `stats_table_query` is still in the 24h aggregate**
  (17,902 events). Rollout cutover at 04:09:51 UTC today, so the window
  covers ~14h of legacy traffic before that point. It'll drop out of
  24h aggregates fully around 04:10 UTC tomorrow.
- **`web_overview_preaggregated_query` fired once** (Section 8). First
  preagg tag emit observed all skill-history. The stats_table preagg
  variants remain at zero.

## 2. Top 30 outliers (>10s)

`r2_outliers_24h.tsv`. Three shape families:

### 2A. Team 2 — PostHog's own project, "🎉 PostHog App + Website"

5 of the top 7 24h outliers:

| time (UTC)   | tag                       | duration | read_rows | memory MB |
| ------------ | ------------------------- | -------- | --------- | --------- |
| 2026-05-19 09:08:26 | `web_goals_query`         | **54,960** | **1.245B**    | **26,021**    |
| 2026-05-18 18:28:08 | `stats_table_query`       | 44,174   | 50.5M     | 4,343     |
| 2026-05-18 18:24:11 | `stats_table_query`*      | 32,979   | 3.1M      | 1,460     |
| 2026-05-18 18:28:11 | `stats_table_query`       | 30,315   | 128.4M    | 3,452     |
| 2026-05-19 09:07:29 | `web_overview_query`      | 27,447   | 727.9M    | 16,847    |

*one of these is team 365368, not team 2 — but same time pattern.

Two distinct sessions on this team: a ~5-minute window at 18:24–18:28 UTC
yesterday with several 30s+ queries, and the 09:07–09:08 UTC monster
event today (54s reading 1.25B rows, 26 GB). Reading the entire
posthog.com event history at once. Probably a single user opening a
dashboard with no date filter or an absurdly long range.

### 2B. The 09:52 UTC cluster slow-down event (NEW finding)

`r6_0952_cluster.tsv` — within 21 seconds (09:51:51 → 09:52:12 UTC),
**7 different teams** hit slow queries:

| time     | team_id | tag                              | duration | read_rows | mem MB |
| -------- | ------- | -------------------------------- | -------- | --------- | ------ |
| 09:51:51 | 248819  | `web_overview_query`             | 5,775    | 1.75M     | 719    |
| 09:52:03 | 234712  | `stats_table_main_query`         | 20,007   | 3.89M     | 728    |
| 09:52:03 | 319398  | `stats_table_main_query`         | 17,092   | 968K      | 728    |
| 09:52:04 | 319398  | `stats_table_main_query`         | 18,577   | 943K      | 726    |
| 09:52:04 | 319398  | `stats_table_path_bounce_query`  | 18,007   | 1.9M      | 1,460  |
| 09:52:04 | 248819  | `stats_table_path_bounce_query`  | 17,766   | 3.55M     | 1,449  |
| 09:52:05 | 430852  | `stats_table_path_bounce_query`  | 12,388   | 273K      | 1,460  |
| 09:52:05 | 416372  | `stats_table_path_bounce_query`  | 9,033    | 1.67M     | 1,460  |
| 09:52:06 | 430852  | `web_overview_query`             | 22,091   | 109K      | 725    |
| 09:52:07 | 234712  | `stats_table_main_query`         | 22,323   | 3.98M     | 733    |
| 09:52:21 | 115294  | `stats_table_main_query`         | 5,868    | 1.0M      | 720    |
| 09:52:22 | 115294  | `web_overview_query`             | 9,815    | 1.02M     | 725    |

Read row counts are **modest** (mostly 1–4M rows). Memory usage is
**unremarkable** (mostly 700–1500 MB). These queries should not have
taken 17–22 seconds. The simultaneous degradation across 7 unrelated
teams + 4 different query shapes within 21 seconds points to
**cluster-level contention**, not query-shape problems.

Notable: this event happened **8 minutes after team 2's 54s monster
finished at 09:08:26**, and **8 minutes before `clusterAllReplicas`
started failing at ~10:00 UTC** (the cluster outage I tracked all
morning). Looks like a 1h-long systemic stress sequence:

1. 08:56–08:57: team 10085 ran 5 consecutive 246M-row, 5GB-memory queries
   (~135 GB cluster memory in 50 min).
2. 09:07–09:08: team 2's 54s, 1.25B-row, 26 GB query.
3. 09:52: 7-team cluster slowdown.
4. 10:00: Metabase ↔ replica connection fails.

These aren't necessarily causally linked, but the temporal correlation
suggests the cluster was under real pressure during this window. Worth a
heads-up to whoever monitors prod-us ONLINE.

### 2C. Personal-API-key tail spikes

Two PAK consumers had outliers in the top-30:

| time     | team_id | tag                  | duration | read_rows | shape         |
| -------- | ------- | -------------------- | -------- | --------- | ------------- |
| 12:17:48 | 204248  | `stats_table_main_query` | 32,439 | 909K      | rapid-fire burst |
| 12:17:49 | 204248  | `web_overview_query` | 33,542   | 765K      | rapid-fire burst |

(Plus team 125691's 10.7s `external_clicks_query` at 11:45:22.)

Both teams' typical-duration profile is 600–1000ms. The 30s+ outliers
are tail events when the team is mid-burst (team 204248 fires ~11
overview queries/minute). Different shape from sections 2A and 2B.

## 3. Hourly timeline — when do slow queries cluster?

`r3_hourly_timeline.tsv`. "Slow buckets" defined as `over_10s ≥ 4`:

| hour (UTC)   | cnt  | over_5s | over_10s | p95 ms | p99 ms |
| ------------ | ---- | ------- | -------- | ------ | ------ |
| 2026-05-18 14:00 | 525 | 0   | 0  | 1128 | 1491 |
| 2026-05-18 15:00 | 4078 | 20  | 2  | 1652 | 3769 |
| 2026-05-18 16:00 | 3683 | 0   | 0  | 1434 | 2285 |
| 2026-05-18 17:00 | 3914 | 8   | 1  | 1636 | 2847 |
| **2026-05-18 18:00** | **4424** | **44** | **17** | 1998 | **4906** |
| 2026-05-18 19:00 | 3552 | 5   | 1  | 1620 | 2803 |
| 2026-05-18 20:00 | 2808 | 9   | 0  | 1657 | 3073 |
| 2026-05-18 21:00 | 2289 | 7   | 3  | 1258 | 3211 |
| 2026-05-18 22:00 | 2832 | 3   | 0  | 1175 | 1905 |
| 2026-05-18 23:00 | 2573 | 20  | 2  | 1609 | 4061 |
| 2026-05-19 00:00 | 2541 | 21  | 3  | 1720 | 4223 |
| 2026-05-19 01:00 | 2510 | 8   | 2  | 1655 | 3442 |
| **2026-05-19 02:00** | 2309 | **33** | 6  | 2306 | **6137** |
| 2026-05-19 03:00 | 2048 | 9   | 0  | 1631 | 3857 |
| **2026-05-19 04:00** | 1899 | **29** | 5  | 2193 | **6200** |
| 2026-05-19 05:00 | 2111 | 12  | 0  | 1424 | 3082 |
| 2026-05-19 06:00 | 2516 | 0   | 0  | 1209 | 2354 |
| 2026-05-19 07:00 | 2197 | 1   | 0  | 1335 | 2111 |
| 2026-05-19 08:00 | 1968 | 16  | 4  | 1695 | 4579 |
| **2026-05-19 09:00** | 2071 | 21 | **10** | 1654 | **5040** |
| 2026-05-19 10:00 | 2416 | 4   | 1  | 1658 | 3066 |
| 2026-05-19 11:00 | 2153 | 2   | 1  | 1334 | 2094 |
| 2026-05-19 12:00 | 3613 | 12  | 4  | 1539 | 2678 |
| 2026-05-19 13:00 | 4030 | 7   | 0  | 1328 | 2320 |
| 2026-05-19 14:00 | 3340 | 9   | 0  | 2006 | 3492 |

**Five hours of elevated slow-query density**:

- **2026-05-18 18:00 UTC**: 17 over_10s, 44 over_5s. The biggest single
  hour of the window. Largely driven by team 2's 18:24–18:28 cluster.
- **2026-05-19 02:00 UTC**: 6 over_10s, 33 over_5s. The morning scheduled
  cluster (Section 4).
- **2026-05-19 04:00 UTC**: 5 over_10s, 29 over_5s. Same scheduled
  cluster, second tick.
- **2026-05-19 09:00 UTC**: 10 over_10s. The systemic stress event
  (Section 2B).

Other notable patterns:

- **06:00 and 07:00 UTC: zero over_5s** — the calmest period of the
  entire day. Coincides with the post-overnight, pre-EU-morning gap.
- **Peak traffic by volume**: 18:00 yesterday (4424), 12:00 today (3613),
  13:00 today (4030). EU/US working hours.
- **Lowest traffic**: 03:00–05:00 UTC (~1900–2100/hr).

## 4. The 02:00 and 04:00 UTC scheduled cluster

Confirmed by the 24h timeline. These two buckets are 2h apart, both with
6-and-5 over_10s queries, both with p99 ~6.2s.

Earlier analysis (`run-0723Z`) identified the team cohort behind these:
**15 teams ran >5s queries** in these windows, and **13 of them had zero
activity in the calm 06:00–06:30 UTC window**. They show up exclusively
at 02:00 and 04:00 UTC.

This is the **scheduled-refresh cohort** — dashboard cron, alerts, or
webhook integrations on fixed-time crons. The natural canary population
for the lazy-precomp feature flag is team **21405**, **298634**,
**227169**, **293278** (highest consistency and latency in slow buckets).

## 5. Top teams by 24h memory burn

`r5_top_teams_24h.tsv`:

| team_id | access | cnt  | over_5s | avg ms | p95 ms | max ms | total memory |
| ------- | ------ | ---- | ------- | ------ | ------ | ------ | ------------ |
| 219890  | UI     | 2611 | 9       | 669    | 1182   | 14,319 | **2.13 TB**  |
| 412542  | UI     | 845  | 4       | 633    | 941    | 6,107  | 720 GB       |
| 360230  | UI     | 777  | 1       | 905    | 1621   | 6,966  | 632 GB       |
| 358951  | UI     | 668  | 2       | 664    | 1160   | 6,189  | 538 GB       |
| 319398  | UI     | 585  | 3       | 664    | 986    | 18,577 | 472 GB       |
| 423176  | UI     | 537  | 1       | 545    | 1235   | 10,150 | 394 GB       |
| 361786  | UI     | 414  | 0       | 874    | 1655   | 3,874  | 354 GB       |

- **Team 219890** ran 2611 queries with healthy p95 (1.2s), but burned
  2.13 TB of cluster memory over 24h. Heavy *interactive* use, not
  polling. They're a power user, not a problem.
- Team 2 (PostHog itself) is **not** in the top-20 by aggregate memory
  despite having the single biggest query (54s, 26 GB). Their volume is
  low; just a few monster queries.
- The "Bucket 2 — heavy scans" teams from earlier analysis (10085,
  112458) aren't in this top-20 either, because their bursts are
  short-lived. The lazy-precomp win is concentrated on a small number
  of high-impact dashboard sessions, not a continuous load.

## 6. Errors and exceptions (24h)

`r4_errors_24h.tsv`. **System is healthy**.

| query_type                             | error                       | cnt | teams |
| -------------------------------------- | --------------------------- | --- | ----- |
| `stats_table_main_query`               | QUERY_WAS_CANCELLED         | 74  | 55    |
| `stats_table_query` (legacy)           | QUERY_WAS_CANCELLED         | 73  | 47    |
| `stats_table_path_bounce_query`        | QUERY_WAS_CANCELLED         | 38  | 31    |
| `stats_table_frustration_metrics_query`| QUERY_WAS_CANCELLED         | 35  | 31    |
| `web_overview_query`                   | QUERY_WAS_CANCELLED         | 25  | 19    |
| `web_goals_query`                      | QUERY_WAS_CANCELLED         | 16  | 13    |
| `stats_table_entry_bounce_query`       | QUERY_WAS_CANCELLED         | 5   | 3     |
| `web_vitals_path_breakdown_query`      | QUERY_WAS_CANCELLED         | 2   | 2     |
| `stats_table_frustration_metrics_query`| TIMEOUT_EXCEEDED (159)      | 1   | 1     |
| `external_clicks_query`                | TIMEOUT_EXCEEDED            | 1   | 1     |
| `stats_table_path_bounce_query`        | TIMEOUT_EXCEEDED            | 1   | 1     |
| `stats_table_query`                    | MEMORY_LIMIT_EXCEEDED (241) | 1   | 1     |
| `stats_table_main_query`               | NO_COMMON_TYPE (386)        | 1   | 1     |
| `external_clicks_query`                | QUERY_WAS_CANCELLED         | 1   | 1     |

- **268 cancellations across 268 user navigations** — benign.
- **3 timeouts in 24h across 68K queries** = a 0.004% timeout rate.
- **1 memory limit hit** — a single team had one heavy query rejected.
- **1 NO_COMMON_TYPE bug recurrence** — the `mat_$viewport_width` String
  vs UInt8 comparison bug. Same query-builder shape we identified in the
  morning. Still affecting team 324931 occasionally.
- **0 TOO_MANY_SIMULTANEOUS_QUERIES** in this 24h window. (The earlier
  morning report saw 39 of these; they must have all been in the
  late-night UTC hours that have aged out of this window.)

## 7. Cluster connectivity issues today

Recurring `ALL_CONNECTION_TRIES_FAILED` against the same ONLINE replica:

| Window (UTC)        | Status   |
| ------------------- | -------- |
| 10:00 → 10:55       | failing  |
| 11:00 → 11:08       | working  |
| 11:40 → 12:44       | failing  |
| 12:44 → 13:50       | working  |
| (intermittent ticks observed in later iterations) |  |

Total cluster blind time: ~2 hours over the morning. Affected both
ONLINE (db 143, CH 25.12.8.9) and OFFLINE (db 142, CH 26.3.10.60)
during the broader window. Same failing replica URI consistently — most
plausible root cause is Metabase-side connectivity or credentials, not
two independent ClickHouse incidents.

Worth flagging to whoever monitors Metabase ↔ ClickHouse routing.

## 8. The preagg modifier (still mostly dead)

The earlier finding "preagg tags are zero in 48h" was specific to
**stats_table** preaggregated variants (`stats_table_preaggregated_*`).
Those remain at zero.

`r1_tags_24h.tsv` does show **one** `web_overview_preaggregated_query`
emit in 24h: 263ms, single team. So the overview-preagg path can fire,
but it's flipped on for essentially zero teams. The path is gated by
`self.modifiers.useWebAnalyticsPreAggregatedTables` — that modifier is
universally off for user-facing dashboards.

The lazy-precomp commit on the current branch fixes this gap by adding
a per-team multivariate flag for `bouncePrecomputationMode`. That's the
right product shape — the existing preagg system has been built but
isn't reachable, while the lazy-precomp system is structured to actually
roll out.

## 9. Implications for the current PR (`adbbff02378`)

Direct evidence from 24h data supporting the lazy-precomp approach:

- `stats_table_path_bounce_query` is the slowest mainstream tag
  (p99 5.2s) and the highest-volume single canonical web-analytics tile
  outside main_query. Targeting it has maximum impact on what users see.
- The 02:00 and 04:00 UTC scheduled clusters are the cleanest test
  population — predictable wall-clock times, off-peak (no concurrent UI
  contention), small known team cohort. Flipping the feature flag for
  teams 21405, 298634, 227169, 293278 and watching the next morning's
  slow buckets is an unambiguous A/B test.
- The "Bucket 2" dashboard heavy-load incidents (teams 2, 10085, 112458)
  generate the largest single bursts of cluster memory. Even single-team
  rollouts (e.g., team 10085 has consistent dashboard usage) would
  visibly cut cluster memory burn.

What this 24h data does NOT support:

- Lazy precomp will not help the personal-API-key polling shapes
  (teams 125691, 204248). Those need request rate-limiting or
  coalescing, separately.
- The 09:52 systemic slowdown isn't a query-shape issue — lazy precomp
  doesn't address infrastructure events.

## Files in this report

- `r1_tags_24h.tsv` — per-tag aggregate, full 24h
- `r2_outliers_24h.tsv` — top-30 queries >10s
- `r3_hourly_timeline.tsv` — 25-hour timeline with over_5s/over_10s
- `r4_errors_24h.tsv` — exception breakdown
- `r5_top_teams_24h.tsv` — top 20 teams by total memory burned
- `r6_0952_cluster.tsv` — detail of the systemic 09:52 slowdown
