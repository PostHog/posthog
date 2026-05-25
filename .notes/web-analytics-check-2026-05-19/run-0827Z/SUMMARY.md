# Web analytics snapshot — 2026-05-19 08:27 UTC (run-0827Z)

Diff vs run-0755Z. The 02:00 slow bucket exited the 6h window during this
iteration, which separates window-slide artifacts from real behavior.

## Headline: real steady-state p95 is meaningfully lower than the 6h aggregates have been showing

| Tag                              | p95 1h ago | p95 now | Δ    |
| -------------------------------- | ---------- | ------- | ---- |
| `stats_table_main_query`         | 1383       | 1227    | −11% |
| `web_overview_query`             | 1586       | 1232    | −22% |
| `stats_table_path_bounce_query`  | 2562       | 2191    | −14% |
| `web_goals_query`                | 2213       | 1794    | −19% |

The 6h window now spans 02:28 → 08:27, so the 02:00 cluster fully exited.
The 04:00 cluster is still partially inside. **One more iteration should
show another step-down** as the 04:00 cluster also rolls out around 10:00Z.

The implication: when sizing the "actual" user-facing p95 for these tags,
ignore the multi-hour window and look at the 06:00 UTC → present band. The
6h-aggregate numbers from earlier today were inflated by the two scheduled
slow clusters. **Real steady-state user p95s:**

- `stats_table_main_query`: ~1.0–1.2s
- `web_overview_query`: ~1.0–1.3s
- `stats_table_path_bounce_query`: ~2.0–2.5s (still the worst stats_table)
- `web_goals_query`: ~1.5–2.0s

## Slow queries during EU morning (last hour)

Only 2 queries over 5s in the last hour:

| team_id | tag                       | duration ms | event_time | access_method |
| ------- | ------------------------- | ----------- | ---------- | ------------- |
| 430628  | `stats_table_main_query`  | 7601        | 08:24:43   | UI            |
| 210253  | `stats_table_main_query`  | 5909        | 07:36:46   | UI            |

Both are UI traffic on `stats_table_main_query` — not path_bounce. Both are
**outside** the 02:00/04:00 scheduled-refresh cohort identified earlier.
These look like real user interactions waiting on slow queries — a genuine
user-pain signal, just at much lower frequency than the scheduled spikes.

**The `main_query` tag, not `path_bounce`, is producing the user-facing
slow-tail during waking hours.** That changes the prioritization a bit:
lazy precomp for path_bounce addresses the scheduled-refresh slow tail
(which is the bigger latency mass), but a follow-up to also lazy-precompute
or otherwise speed up the `main_query` path would address the interactive
user-pain slow tail. Different shape, both worth doing.

## Other observations

- `stats_table_query` (legacy) down to 96 (from 136). Last seen still
  04:15:19Z. Should hit zero around 10:15Z when that timestamp rolls out
  of the 6h window.
- `external_clicks_query` count keeps climbing (186 → 211) as the new tag
  rollout matures. p95 down to 1816ms — getting closer to a steady value.
- `stats_table_path_bounce_and_avg_time_query` still showing the single
  07:09:59Z emit. No new fires.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 6022    | 6157      | 1227    | 1383      |
| `web_overview_query`                    | 2467    | 2549      | 1232    | 1586      |
| `stats_table_frustration_metrics_query` | 1898    | 1912      | 1057    | 1183      |
| `stats_table_path_bounce_query`         | 1880    | 1900      | 2191    | 2562      |
| `web_vitals_path_breakdown_query`       | 385     | 367       | 477     | 481       |
| `web_goals_query`                       | 340     | 346       | 1794    | 2213      |
| `stats_table_entry_bounce_query`        | 219     | 225       | 1538    | 1850      |
| `external_clicks_query`                 | 211     | 186       | 1816    | 1940      |
| `stats_table_query` (legacy)            | 96      | 136       | 1476    | 1813      |
| `stats_table_path_bounce_and_avg_time_query` | 1   | 1         | 2280    | 2280      |

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q22_slow_last_hour.tsv` — 2 slow queries in last hour, both team-distinct

## Watch list for next iteration

1. Confirm the next p95 step-down at ~10:00Z (when 04:00 cluster exits).
2. Whether the user-pain slow-tail on `main_query` continues to show up
   sporadically during peak hours (i.e., is the 08:24 7.6s query a one-off
   or a recurring shape).
3. `stats_table_query` (legacy) hitting zero — probably around 10:15Z.
