# Web analytics snapshot — 2026-05-19 16:33 UTC (run-1633Z)

First iteration with the cross-iteration trendline. p95 creeping up across
several tags over the last hour — looks like EU-end-of-day + US-ramp
contention.

## Cross-iteration trendline (last 9 ticks, post cluster-recovery)

p95 latency (ms) per tag across iterations. Cluster query was unreliable
before 11:08Z, so the trendline starts there.

| Tag                     | 11:08 | 12:44 | 13:17 | 13:49 | 14:21 | 14:57 | 15:29 | 16:01 | **16:33** | Δ vs 11:08 |
| ----------------------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | --------- | ---------- |
| `main_query`            | 1,278 | 1,378 | 1,337 | 1,306 | 1,311 | 1,380 | 1,391 | 1,406 | **1,457** | **+14%**   |
| `web_overview`          | 1,207 | 1,310 | 1,262 | 1,243 | 1,291 | 1,356 | 1,389 | 1,388 | **1,430** | **+18%**   |
| `frustration_metrics`   | 1,255 | 1,263 | 1,212 | 1,201 | 1,262 | 1,295 | 1,341 | 1,323 | **1,373** | +9%        |
| **`path_bounce`**       | 2,372 | 2,436 | 2,391 | 2,334 | 2,373 | 2,550 | 2,615 | 2,590 | **2,683** | **+13%**   |
| `vitals`                | 607   | 729   | 680   | 679   | 727   | 791   | 819   | 854   | **837**   | +38%       |
| `web_goals`             | 2,300 | 2,356 | 2,357 | 2,457 | 2,428 | 2,480 | 2,521 | 2,368 | **2,354** | +2%        |
| `entry_bounce`          | 1,107 | 1,299 | 1,296 | 1,313 | 1,258 | 1,343 | 1,412 | 1,367 | **1,567** | **+42%**   |
| `external_clicks`       | 1,381 | 2,308 | 2,102 | 2,073 | 1,959 | 1,811 | 2,303 | 2,304 | **2,327** | +69%       |

Volume (count in 6h window) for context:

| Tag                     | 11:08 | 13:17 | 14:21 | 14:57 | 15:29 | 16:01 | **16:33** |
| ----------------------- | ----- | ----- | ----- | ----- | ----- | ----- | --------- |
| `main_query`            | 6,101 | 6,896 | 7,661 | 8,263 | 8,537 | 8,998 | **9,122** |
| `web_overview`          | 2,267 | 2,624 | 2,945 | 3,142 | 3,310 | 3,502 | **3,613** |
| `frustration_metrics`   | 1,940 | 2,168 | 2,393 | 2,546 | 2,621 | 2,763 | **2,803** |
| `path_bounce`           | 1,874 | 2,070 | 2,319 | 2,482 | 2,577 | 2,713 | **2,760** |
| `external_clicks`       | 90    | 148   | 195   | 230   | 245   | 283   | **298**   |

Max latency (ms) — extreme outliers in window:

| Tag                  | 11:08 | 12:44 | 14:57 | 15:29 | 16:01 | **16:33** | notable change      |
| -------------------- | ----- | ----- | ----- | ----- | ----- | --------- | ------------------- |
| `main_query`         | 22,323| 32,439| 32,439| 32,439| 32,439| 32,439    | team 204248 12:17   |
| `web_overview`       | 27,447| 33,542| 33,542| 33,542| 33,542| 33,542    | team 204248 12:17   |
| `path_bounce`        | 18,007| 20,099| 20,099| 20,099| 20,099| 20,099    | team 112458 12:43   |
| `frustration`        | 7,809 | 7,809 | 4,561 | 4,561 | 5,117 | **6,508** | bouncing outliers   |
| `vitals`             | 1,614 | 1,614 | 3,263 | 4,493 | 4,493 | 4,493     | team 234917 14:44   |
| `web_goals`          | 54,960| 54,960| 54,960| 9,804 | 9,804 | 9,804     | team 2 monster aged out |
| `entry_bounce`       | 2,620 | 2,620 | 3,380 | 3,380 | 3,380 | **3,607** | new outlier         |
| `external_clicks`    | 1,565 | 10,654| 10,654| 42,828| 42,828| 42,828    | team 125691 15:15   |

### Read of the trendline

- **Steady upward p95 drift across most tags over the last hour.**
  main_query +14%, overview +18%, path_bounce +13% from 11:08 → 16:33.
  Volume is also up (+50% on main_query in the same span). Volume + p95
  both rising = real traffic contention, not just window-slide.
- **External_clicks p95 +69%** is the standout, but it's noisy due to
  team 125691's polling tail-spikes — the 15:15 incident (42.8s) put a
  big single-team contribution in this window.
- **Vitals p95 +38%** is mostly counting team 234917's 14:44 dashboard
  load entering the window.
- **`web_goals` is the only tag tracking flat** (+2% — within noise).
  Volume on goals is much lower (418 vs 9,122 main_query in 6h), so it
  responds less to broad contention.
- The 6h window now spans 10:33 → 16:33 UTC — the morning 02:00/04:00
  scheduled clusters and team 2's monster have all aged out, so all
  numbers represent **steady-state EU/US working-hours traffic**.

The creep is most plausibly **EU end-of-day overlapping with US morning**
producing concurrent dashboard refreshes. Worth watching the next 1–2
iterations to see if path_bounce p95 settles back down or continues
rising as US peak kicks in.

## New outlier this tick

- `stats_table_entry_bounce_query`: max **3,380 → 3,607 ms**. Small step.
- `stats_table_frustration_metrics_query`: max **5,117 → 6,508 ms**.
  Another small fresh outlier in this tag (third bump in 3 iterations).

Neither is concerning individually. Both fit the steady creep narrative.

## Headline tag aggregate (this tick)

| Tag                                          | cnt   | avg ms | p95 ms | p99 ms | max ms |
| -------------------------------------------- | ----- | ------ | ------ | ------ | ------ |
| `stats_table_main_query`                     | 9,122 | 719    | 1,457  | 2,610  | 32,439 |
| `web_overview_query`                         | 3,613 | 709    | 1,430  | 2,680  | 33,542 |
| `stats_table_frustration_metrics_query`      | 2,803 | 663    | 1,373  | 2,252  | 6,508  |
| `stats_table_path_bounce_query`              | 2,760 | 1,331  | 2,683  | 5,144  | 20,099 |
| `web_vitals_path_breakdown_query`            | 588   | 344    | 837    | 1,282  | 4,493  |
| `web_goals_query`                            | 418   | 1,014  | 2,354  | 6,081  | 9,804  |
| `stats_table_entry_bounce_query`             | 354   | 733    | 1,567  | 2,637  | 3,607  |
| `external_clicks_query`                      | 298   | 1,216  | 2,327  | 10,669 | 42,828 |
| `stats_table_path_bounce_and_avg_time_query` | 1     | 3,006  | 3,006  | 3,006  | 3,006  |

## Cluster: stable

`clusterAllReplicas` first try. ~4 hours since the last outage tick.

## Files

- `q11b_all_web_tags_6h.tsv` — current per-tag aggregate

## Watch list for next iteration

1. Whether path_bounce p95 continues rising (2683 → ?) or settles. US
   peak should land in the next 1–2 hours.
2. Whether external_clicks p99 normalizes as team 125691's 42.8s outlier
   moves toward the edge of the 6h window (event was at 15:15:49 UTC,
   exits at 21:15:49 UTC).
3. The new entry_bounce and frustration max bumps — recurring or
   one-shot?
