# Web analytics snapshot — 2026-05-19 17:43 UTC (run-1743Z)

**Headline: preaggregated tags fired for the first time in 48h+ of
monitoring. Team 39058 — single user — produced 12 sub-500ms preagg
queries in 31 seconds.**

## Preaggregated path went live (for one team)

`q41_preagg_source.tsv` — all 12 preagg queries in the 17:18:30 → 17:19:30 UTC window:

| time     | tag                                              | duration | read_rows |
| -------- | ------------------------------------------------ | -------- | --------- |
| 17:18:36 | `stats_table_preaggregated_query`                | 167      | 8.4M      |
| 17:18:36 | `stats_table_preaggregated_path_breakdown_query` | 193      | 14.2M     |
| 17:18:36 | `stats_table_preaggregated_query`                | 94       | 8.4M      |
| 17:18:36 | `web_overview_preaggregated_query`               | 105      | 5.9M      |
| 17:18:47 | `stats_table_preaggregated_query`                | 149      | 18.3M     |
| 17:18:47 | `web_overview_preaggregated_query`               | 144      | 12.4M     |
| 17:18:48 | `stats_table_preaggregated_query`                | 217      | 18.3M     |
| 17:18:48 | `stats_table_preaggregated_path_breakdown_query` | 298      | 30.7M     |
| 17:19:07 | `web_overview_preaggregated_query`               | 291      | 12.9M     |
| 17:19:07 | `stats_table_preaggregated_path_breakdown_query` | 423      | 33.9M     |
| 17:19:07 | `stats_table_preaggregated_query`                | 257      | 21.0M     |
| 17:19:07 | `stats_table_preaggregated_query`                | 252      | 21.0M     |

All from **team 39058, user 56062, UI traffic**. Three back-to-back
dashboard refresh batches (17:18:36, 17:18:47-48, 17:19:07).

### Preagg vs live: ~5–7× faster on identical workloads

| Tag (live)                       | typical UI duration | row scan |
| -------------------------------- | ------------------- | -------- |
| `stats_table_path_bounce_query`  | 1.5–3.0s            | 11–25M   |
| `web_overview_query`             | 1.0–1.5s            | 5–10M    |
| `stats_table_main_query`         | 0.7–1.4s            | 5–15M    |

| Tag (preagg)                                     | duration | row scan |
| ------------------------------------------------ | -------- | -------- |
| `stats_table_preaggregated_path_breakdown_query` | 193–423  | 14–34M   |
| `web_overview_preaggregated_query`               | 105–291  | 6–13M    |
| `stats_table_preaggregated_query`                | 94–257   | 8–21M    |

Same row counts, ~5–7× faster. Preagg path is functionally correct and
delivers the expected speedup. **This is the first concrete prod
measurement of the preagg path working.**

Worth noting: this is *not* the lazy-precomp path from the current
branch — it's the existing Dagster-fed preagg path that's been gated
behind `modifiers.useWebAnalyticsPreAggregatedTables` (universally off
until just now). Someone flipped the modifier on for team 39058. The
fact that it returned in 100–400ms confirms the Dagster preagg tables
exist and serve correctly.

The lazy-precomp work this PR addresses is the **rollout mechanism** —
per-team feature flag wiring — for this same kind of speedup, applied
to path-bounce specifically.

## Cross-iteration trendline (last 11 ticks)

**p95 latency (ms):**

| Tag                     | 11:08 | 12:44 | 13:17 | 13:49 | 14:21 | 14:57 | 15:29 | 16:01 | 16:33 | 17:10 | **17:43** | Δ vs 17:10 | Δ vs 11:08 |
| ----------------------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | --------- | ---------- | ---------- |
| `main_query`            | 1,278 | 1,378 | 1,337 | 1,306 | 1,311 | 1,380 | 1,391 | 1,406 | 1,457 | 1,472 | **1,505** | +2%        | +18%       |
| `web_overview`          | 1,207 | 1,310 | 1,262 | 1,243 | 1,291 | 1,356 | 1,389 | 1,388 | 1,430 | 1,449 | **1,496** | +3%        | +24%       |
| `frustration_metrics`   | 1,255 | 1,263 | 1,212 | 1,201 | 1,262 | 1,295 | 1,341 | 1,323 | 1,373 | 1,371 | **1,392** | +2%        | +11%       |
| `path_bounce`           | 2,372 | 2,436 | 2,391 | 2,334 | 2,373 | 2,550 | 2,615 | 2,590 | 2,683 | 2,666 | **2,698** | +1%        | +14%       |
| `vitals`                | 607   | 729   | 680   | 679   | 727   | 791   | 819   | 854   | 837   | 832   | **837**   | flat       | +38%       |
| **`web_goals`**         | 2,300 | 2,356 | 2,357 | 2,457 | 2,428 | 2,480 | 2,521 | 2,368 | 2,354 | 2,304 | **2,543** | **+10%**   | +11%       |
| **`entry_bounce`**      | 1,107 | 1,299 | 1,296 | 1,313 | 1,258 | 1,343 | 1,412 | 1,367 | 1,567 | 1,838 | **1,664** | **−9%**    | +50%       |
| `external_clicks`       | 1,381 | 2,308 | 2,102 | 2,073 | 1,959 | 1,811 | 2,303 | 2,304 | 2,327 | 2,305 | **2,295** | flat       | +66%       |

**Volume (cnt in 6h window):**

| Tag                     | 11:08 | 14:21 | 14:57 | 15:29 | 16:01 | 16:33 | 17:10 | **17:43** |
| ----------------------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | --------- |
| `main_query`            | 6,101 | 7,661 | 8,263 | 8,537 | 8,998 | 9,122 | 9,585 | **10,102**|
| `web_overview`          | 2,267 | 2,945 | 3,142 | 3,310 | 3,502 | 3,613 | 3,875 | **4,063** |
| `path_bounce`           | 1,874 | 2,319 | 2,482 | 2,577 | 2,713 | 2,760 | 2,896 | **3,037** |
| `external_clicks`       | 90    | 195   | 230   | 245   | 283   | 298   | 321   | **352**   |

**Preagg volume (new this tick):**

| Tag                                              | cnt | first_seen | last_seen |
| ------------------------------------------------ | --- | ---------- | --------- |
| `stats_table_preaggregated_query`                | 6   | 17:18:36   | 17:19:07  |
| `stats_table_preaggregated_path_breakdown_query` | 3   | 17:18:36   | 17:19:07  |
| `web_overview_preaggregated_query`               | 3   | 17:18:36   | 17:19:07  |

### Read of the trendline

- **The "creep peaked" call from last tick was premature.** Most p95s
  moved up again this iteration: main +2%, overview +3%, frustration +2%.
  Path_bounce barely moved (+1%). So we're still in the slow EU/US peak
  contention, but the rate of rise has flattened.
- **`web_goals` p95 +10%** (2,304 → 2,543) — most significant move this
  tick. Max unchanged at 9,804 ms, so no new extreme outlier. Looks like
  several mid-tail (4–6s) goals queries entered the window. Worth a
  quick check next tick.
- **`entry_bounce` spike was transient** (-9%, 1,838 → 1,664). Last
  tick's +17% was a short-lived cluster, not a sustained shift.
- **Volume continues climbing steadily** (+517 main_query in 33 min).

## Per-tag aggregate (this tick)

| Tag                                                | cnt    | avg ms | p95 ms | p99 ms | max ms |
| -------------------------------------------------- | ------ | ------ | ------ | ------ | ------ |
| `stats_table_main_query`                           | 10,102 | 737    | 1,505  | 2,758  | 32,439 |
| `web_overview_query`                               | 4,063  | 717    | 1,496  | 2,686  | 33,542 |
| `stats_table_frustration_metrics_query`            | 3,070  | 678    | 1,392  | 2,458  | 6,508  |
| `stats_table_path_bounce_query`                    | 3,037  | 1,354  | 2,698  | 5,422  | 20,099 |
| `web_vitals_path_breakdown_query`                  | 649    | 345    | 837    | 1,253  | 4,493  |
| `web_goals_query`                                  | 485    | 1,057  | 2,543  | 6,125  | 9,804  |
| `stats_table_entry_bounce_query`                   | 384    | 767    | 1,664  | 3,055  | 3,607  |
| `external_clicks_query`                            | 352    | 1,153  | 2,295  | 9,595  | 42,828 |
| **`stats_table_preaggregated_query`**              | **6**  | **189**| **256**| **257**| **257**|
| **`stats_table_preaggregated_path_breakdown_query`**| **3** | **305**| **411**| **421**| **423**|
| **`web_overview_preaggregated_query`**             | **3**  | **180**| **276**| **288**| **291**|
| `stats_table_path_bounce_and_avg_time_query`       | 1      | 3,006  | 3,006  | 3,006  | 3,006  |

## Cluster: stable

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate (now 12 rows with preagg!)
- `q41_preagg_source.tsv` — the 12 preagg queries, team 39058 source

## Watch list for next iteration

1. **Whether team 39058 keeps firing preagg queries** (sustained rollout
   or one-shot test?). The lazy-precomp PR effectively does this same
   thing but per-team via flag — important to know if the existing
   Dagster preagg can be relied on as the comparison baseline.
2. Whether `web_goals` p95 +10% sustains or normalizes.
3. Path_bounce p95 — has it peaked at ~2,700 ms?
