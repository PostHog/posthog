# Web analytics snapshot — 2026-05-19 05:13 UTC (run-0513Z)

Diff vs run-0438Z. Last 6h window, prod-us ONLINE.

## Headline: legacy `stats_table_query` is dead

`q12_timeline_8h.tsv` confirms full rollout convergence. 15-min buckets:

| Bucket (UTC)        | legacy | main_q | path_bounce |
| ------------------- | ------ | ------ | ----------- |
| 2026-05-19 04:00    | 14     | 278    | 74          |
| 2026-05-19 04:15    | 3      | 167    | 64          |
| **2026-05-19 04:30**| **0**  | 233    | 88          |
| 2026-05-19 04:45    | 0      | 173    | 64          |
| 2026-05-19 05:00    | 0      | 220    | 84          |

Last `stats_table_query` event: 2026-05-19 04:15:19 UTC. Three consecutive empty
buckets after that. Rollout of the per-strategy split is complete on prod-us.

Implication: future runs can drop the legacy tag from queries, and the q1
hardcoded list in `/tmp/wa_q1_tag_dist.sql` no longer needs `stats_table_query`.

## Preaggregated tags still zero (8h)

`preagg` column in `q12_timeline_8h.tsv` is 0 across all 33 buckets. None of
`stats_table_preaggregated_query`, `_path_breakdown_query`, or
`_entry_bounce_query` have fired in 8h. Either the preagg modifier is
universally off, or it's wired so it falls back to live before tagging. Worth
inspecting `_resolve_strategy()` in `stats_table.py` to confirm.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 6487    | 6656      | 1558    | 1510      |
| `web_overview_query`                    | 2732    | 2795      | 1714    | 1627      |
| `stats_table_path_bounce_query`         | 2043    | 2078      | 3022    | 2951      |
| `stats_table_frustration_metrics_query` | 2018    | 2069      | 1364    | 1312      |
| `web_vitals_path_breakdown_query`       | 350     | 350       | 533     | 539       |
| `web_goals_query`                       | 292     | 278       | 3667    | 3612      |
| `stats_table_query` (legacy)            | 267     | 291       | 1782    | 1772      |
| `stats_table_entry_bounce_query`        | 178     | 193       | 2379    | 2331      |
| `external_clicks_query`                 | 42      | 12        | **5018**| 2375      |

Drift, not step changes — except `external_clicks_query`: count 3.5×'d and p95
doubled. Still small sample (42 in 6h), but watch this. Two possibilities:

1. Rollout continued — more pods are emitting the new tag, so we're seeing
   a fuller picture of the actual workload (some of which is slow).
2. A specific team's traffic landed in this window.

Worth a follow-up `route_id`/`team_id` slice in the next iteration if it
persists.

## Path bounce remains the slow tail

`stats_table_path_bounce_query`: p95 3.02s, p99 6.72s, max **26.2s** this
window (up from 17.3s prior). The 26s outlier is one query — worth sampling
the `query_id` if max latency keeps moving. But p95/p99 are stable so this is
isolated.

This is still the target the current branch's lazy-precomp work addresses.

## Files in this run

- `q11b_all_web_tags_6h.tsv` — per-tag 6h aggregate
- `q12_timeline_8h.tsv` — 15-min timeline showing legacy tag death at 04:15Z

## Watch list for next iteration

1. `external_clicks_query` p95 — sustained or transient?
2. `stats_table_path_bounce_query` max — is the 26s outlier recurring?
3. Whether `stats_table_preaggregated*` ever fires.
