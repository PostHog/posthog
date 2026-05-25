# Web analytics snapshot — 2026-05-19 17:10 UTC (run-1710Z)

The creep peaked. Most p95s flat or trending down. `path_bounce` finally
stabilized; `entry_bounce` spiked +17% but no new outliers.

## Cross-iteration trendline (last 10 ticks, post cluster-recovery)

**p95 latency (ms):**

| Tag                     | 11:08 | 12:44 | 13:17 | 13:49 | 14:21 | 14:57 | 15:29 | 16:01 | 16:33 | **17:10** | Δ vs 16:33 | Δ vs 11:08 |
| ----------------------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | --------- | ---------- | ---------- |
| `main_query`            | 1,278 | 1,378 | 1,337 | 1,306 | 1,311 | 1,380 | 1,391 | 1,406 | 1,457 | **1,472** | +1%        | +15%       |
| `web_overview`          | 1,207 | 1,310 | 1,262 | 1,243 | 1,291 | 1,356 | 1,389 | 1,388 | 1,430 | **1,449** | +1%        | +20%       |
| `frustration_metrics`   | 1,255 | 1,263 | 1,212 | 1,201 | 1,262 | 1,295 | 1,341 | 1,323 | 1,373 | **1,371** | flat       | +9%        |
| **`path_bounce`**       | 2,372 | 2,436 | 2,391 | 2,334 | 2,373 | 2,550 | 2,615 | 2,590 | 2,683 | **2,666** | **−1%**    | +12%       |
| `vitals`                | 607   | 729   | 680   | 679   | 727   | 791   | 819   | 854   | 837   | **832**   | flat       | +37%       |
| `web_goals`             | 2,300 | 2,356 | 2,357 | 2,457 | 2,428 | 2,480 | 2,521 | 2,368 | 2,354 | **2,304** | **−2%**    | flat       |
| **`entry_bounce`**      | 1,107 | 1,299 | 1,296 | 1,313 | 1,258 | 1,343 | 1,412 | 1,367 | 1,567 | **1,838** | **+17%**   | +66%       |
| `external_clicks`       | 1,381 | 2,308 | 2,102 | 2,073 | 1,959 | 1,811 | 2,303 | 2,304 | 2,327 | **2,305** | flat       | +67%       |

**Volume (cnt in 6h window):**

| Tag                     | 11:08 | 13:17 | 14:21 | 14:57 | 15:29 | 16:01 | 16:33 | **17:10** |
| ----------------------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | --------- |
| `main_query`            | 6,101 | 6,896 | 7,661 | 8,263 | 8,537 | 8,998 | 9,122 | **9,585** |
| `web_overview`          | 2,267 | 2,624 | 2,945 | 3,142 | 3,310 | 3,502 | 3,613 | **3,875** |
| `path_bounce`           | 1,874 | 2,070 | 2,319 | 2,482 | 2,577 | 2,713 | 2,760 | **2,896** |
| `external_clicks`       | 90    | 148   | 195   | 230   | 245   | 283   | 298   | **321**   |

**Max latency (ms):**

| Tag                  | 11:08  | 14:57  | 15:29  | 16:01  | 16:33  | **17:10** | source              |
| -------------------- | ------ | ------ | ------ | ------ | ------ | --------- | ------------------- |
| `main_query`         | 22,323 | 32,439 | 32,439 | 32,439 | 32,439 | 32,439    | team 204248 12:17   |
| `web_overview`       | 27,447 | 33,542 | 33,542 | 33,542 | 33,542 | 33,542    | team 204248 12:17   |
| `path_bounce`        | 18,007 | 20,099 | 20,099 | 20,099 | 20,099 | 20,099    | team 112458 12:43   |
| `frustration`        | 7,809  | 4,561  | 4,561  | 5,117  | 6,508  | 6,508     | small fresh tail    |
| `vitals`             | 1,614  | 3,263  | 4,493  | 4,493  | 4,493  | 4,493     | team 234917 14:44   |
| `web_goals`          | 54,960 | 54,960 | 9,804  | 9,804  | 9,804  | 9,804     | team 2 aged out     |
| `entry_bounce`       | 2,620  | 3,380  | 3,380  | 3,380  | 3,607  | 3,607     | small fresh tail    |
| `external_clicks`    | 1,565  | 10,654 | 42,828 | 42,828 | 42,828 | 42,828    | team 125691 15:15   |

### Read of the trendline

- **The creep has peaked.** 5 of 8 tags are flat or down vs 16:33Z. The
  hour-long upward drift in `main_query` / `overview` / `path_bounce` from
  ~14:30Z onward has leveled off — consistent with the EU-end-of-day +
  US-morning concurrency hypothesis playing out and then easing.
- **`path_bounce` p95 went −1%** (2,683 → 2,666). First flat-to-negative
  tick after 4 consecutive rises. No new outliers; this looks like the
  peak.
- **`entry_bounce` p95 spiked +17%** (1,567 → 1,838). Max unchanged
  (3,607), so it's not a single big outlier — looks like more queries
  clustering in the 1.5–2s range. Worth a glance but not alarming.
- **`web_goals` p95 −2%** continues drifting down as the day's earliest
  slow goals events age out.
- Volume on `main_query` is up another 463 in 37 min — about the same
  steady rate. No volume spike either, so the p95 stabilization is real,
  not a denominator artifact.

## Per-tag aggregate (this tick)

| Tag                                          | cnt   | avg ms | p95 ms | p99 ms | max ms |
| -------------------------------------------- | ----- | ------ | ------ | ------ | ------ |
| `stats_table_main_query`                     | 9,585 | 724    | 1,472  | 2,678  | 32,439 |
| `web_overview_query`                         | 3,875 | 709    | 1,449  | 2,635  | 33,542 |
| `stats_table_frustration_metrics_query`      | 2,939 | 666    | 1,371  | 2,274  | 6,508  |
| `stats_table_path_bounce_query`              | 2,896 | 1,331  | 2,666  | 5,114  | 20,099 |
| `web_vitals_path_breakdown_query`            | 614   | 341    | 832    | 1,265  | 4,493  |
| `web_goals_query`                            | 459   | 1,006  | 2,304  | 6,005  | 9,804  |
| `stats_table_entry_bounce_query`             | 379   | 766    | 1,838  | 3,057  | 3,607  |
| `external_clicks_query`                      | 321   | 1,196  | 2,305  | 10,239 | 42,828 |
| `stats_table_path_bounce_and_avg_time_query` | 1     | 3,006  | 3,006  | 3,006  | 3,006  |

## Cluster: stable

`clusterAllReplicas` worked first try. ~4.5 hours since last outage tick.

## Side note: pending tag rename

The branch `lricoy/web-analytics-simple-breakdown-tag-split` (queued for
review/merge) will rename `stats_table_main_query` →
`stats_table_simple_breakdown_query` and carve out
`stats_table_channel_type_query` from it. When that merges and deploys,
expect another N-hour rollout overlap window (similar to today's
04:10Z legacy-tag death), and the trendline will need new columns.

## Files

- `q11b_all_web_tags_6h.tsv` — current per-tag aggregate

## Watch list for next iteration

1. Whether path_bounce p95 starts trending down (confirming the peak
   passed) or holds flat.
2. Whether entry_bounce spike sustains or was transient.
3. Whether external_clicks p99 keeps drifting down toward "normal" as
   team 125691's 42.8s outlier ages out at 21:15:49Z.
