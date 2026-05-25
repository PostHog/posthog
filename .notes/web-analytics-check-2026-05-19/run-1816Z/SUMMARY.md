# Web analytics snapshot — 2026-05-19 18:16 UTC (run-1816Z)

Preagg burst from 17:18 was a one-shot — no new preagg activity. Other
tags broadly stabilizing.

## Preagg follow-up: one-shot test, not a sustained rollout

`stats_table_preaggregated_query` etc. all still show the same 6/3/3
events from team 39058's 17:18:36 → 17:19:07 window. **Zero new preagg
emits in the last 57 minutes.** So this was a manual test/canary by
someone (possibly a teammate validating the preagg path), then they
turned it back off.

Conclusion still holds: the existing Dagster preagg path **works** and
delivers ~5–7× speedup, but it's gated on a modifier nothing flips on
in normal user traffic. The lazy-precomp PR's per-team flag mechanism
is the missing piece that would make this sustained instead of one-shot.

## Cross-iteration trendline (last 12 ticks)

**p95 latency (ms):**

| Tag                     | 11:08 | 13:17 | 14:21 | 14:57 | 15:29 | 16:01 | 16:33 | 17:10 | 17:43 | **18:16** | Δ vs 17:43 |
| ----------------------- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | --------- | ---------- |
| `main_query`            | 1,278 | 1,337 | 1,311 | 1,380 | 1,391 | 1,406 | 1,457 | 1,472 | 1,505 | **1,470** | **−2%**    |
| `web_overview`          | 1,207 | 1,262 | 1,291 | 1,356 | 1,389 | 1,388 | 1,430 | 1,449 | 1,496 | **1,483** | **−1%**    |
| `frustration_metrics`   | 1,255 | 1,212 | 1,262 | 1,295 | 1,341 | 1,323 | 1,373 | 1,371 | 1,392 | **1,406** | +1%        |
| `path_bounce`           | 2,372 | 2,391 | 2,373 | 2,550 | 2,615 | 2,590 | 2,683 | 2,666 | 2,698 | **2,718** | +1%        |
| `vitals`                | 607   | 680   | 727   | 791   | 819   | 854   | 837   | 832   | 837   | **781**   | **−7%**    |
| `web_goals`             | 2,300 | 2,357 | 2,428 | 2,480 | 2,521 | 2,368 | 2,354 | 2,304 | 2,543 | **2,504** | **−2%**    |
| `entry_bounce`          | 1,107 | 1,296 | 1,258 | 1,343 | 1,412 | 1,367 | 1,567 | 1,838 | 1,664 | **1,599** | **−4%**    |
| **`external_clicks`**   | 1,381 | 2,102 | 1,959 | 1,811 | 2,303 | 2,304 | 2,327 | 2,305 | 2,295 | **1,713** | **−25%**   |

**Volume (cnt in 6h window):**

| Tag             | 11:08 | 14:57 | 16:01 | 16:33 | 17:10 | 17:43 | **18:16** |
| --------------- | ----- | ----- | ----- | ----- | ----- | ----- | --------- |
| `main_query`    | 6,101 | 8,263 | 8,998 | 9,122 | 9,585 | 10,102| **10,386**|
| `web_overview`  | 2,267 | 3,142 | 3,502 | 3,613 | 3,875 | 4,063 | **4,203** |
| `path_bounce`   | 1,874 | 2,482 | 2,713 | 2,760 | 2,896 | 3,037 | **3,136** |
| `vitals`        | 352   | 560   | 588   | 614   | 649   | 649   | **572**   |
| `external_clicks` | 90  | 230   | 283   | 298   | 321   | 352   | **365**   |

### Read of the trendline

- **The creep finally rolled over.** main_query and overview both went
  −1 to −2% this tick — the first negative move on these two leaders
  since the creep started around 14:21Z.
- **`external_clicks` p99 collapsed** (9,595 → 6,009 ms, −37%) and p95
  dropped −25%. Team 125691's 42.8s spike from 15:15Z is now far enough
  into the past that it's losing weight in the percentile calculation.
  Will continue dropping until it ages out at 21:15Z.
- **`vitals` count dropped** (649 → 572) — first time volume decreased
  on any tag. p95 also dropped −7% (837 → 781). The drop in volume
  suggests team 234917's 14:44Z dashboard burst is aging out of the
  window now.
- **`path_bounce` keeps creeping** (+1%) — only tag still trending up.
  Now 14% above the 11:08Z baseline. Worth watching whether it follows
  main_query down in the next tick.
- **`web_goals` normalized** (2,543 → 2,504, −2%) — last tick's +10%
  bump was a one-shot, not a sustained pattern.

## Per-tag aggregate (this tick)

| Tag                                                | cnt    | avg ms | p95 ms | p99 ms | max ms |
| -------------------------------------------------- | ------ | ------ | ------ | ------ | ------ |
| `stats_table_main_query`                           | 10,386 | 734    | 1,470  | 2,754  | 32,439 |
| `web_overview_query`                               | 4,203  | 716    | 1,483  | 2,688  | 33,542 |
| `stats_table_frustration_metrics_query`            | 3,177  | 685    | 1,406  | 2,472  | **7,427** ← +14% |
| `stats_table_path_bounce_query`                    | 3,136  | 1,358  | 2,718  | 5,564  | 20,099 |
| `web_vitals_path_breakdown_query`                  | 572    | 337    | 781    | 1,235  | 4,493  |
| `web_goals_query`                                  | 498    | 1,028  | 2,504  | 6,113  | 9,804  |
| `stats_table_entry_bounce_query`                   | 390    | 765    | 1,599  | 3,052  | 3,607  |
| `external_clicks_query`                            | 365    | 1,052  | 1,713  | 6,009  | 42,828 |
| `stats_table_preaggregated_query`                  | 6      | 189    | 256    | 257    | 257    |
| `stats_table_preaggregated_path_breakdown_query`   | 3      | 305    | 411    | 421    | 423    |
| `web_overview_preaggregated_query`                 | 3      | 180    | 276    | 288    | 291    |
| `stats_table_path_bounce_and_avg_time_query`       | 1      | 3,006  | 3,006  | 3,006  | 3,006  |

`frustration` max nudged up (6,508 → 7,427) — small new outlier. Worth a
glance but not blocker.

## Cluster: stable

`clusterAllReplicas` worked. ~5.5h since last outage.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate

## Watch list for next iteration

1. Whether `path_bounce` p95 follows main_query down (real peak passed)
   or keeps creeping.
2. Whether team 39058 fires preagg queries again — that would suggest
   real rollout, not just a test.
3. `external_clicks` p99 trajectory toward team 125691's outlier
   aging out at 21:15Z.
