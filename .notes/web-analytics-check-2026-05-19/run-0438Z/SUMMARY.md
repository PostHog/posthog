# Web analytics snapshot — 2026-05-19 04:38 UTC (run-0438Z)

## Correction to prior run

Previous iteration (`../SUMMARY.md`) claimed `stats_table_query` was a single
catch-all tag and that splitting it was a follow-up. **Already done on
`origin/master`.** My local master was stale. After `git fetch`:

- `external_clicks.py:116` already emits `query_type="external_clicks_query"`
- `stats_table.py` has `clickhouse_query_type()` returning per-strategy tags
  (`stats_table_main_query`, `stats_table_path_bounce_query`,
  `stats_table_frustration_metrics_query`,
  `stats_table_path_bounce_and_avg_time_query`, `stats_table_entry_bounce_query`,
  plus the 3 preaggregated variants)

Both rollouts are in flight in the data this iteration captures.

## Per-strategy distribution (last 6h, `stats_table%` only)

| Tag                                         | cnt  | avg ms | p95 ms   | p99 ms   |
| ------------------------------------------- | ---- | ------ | -------- | -------- |
| `stats_table_main_query`                    | 6656 | 700    | 1510     | 4100     |
| **`stats_table_path_bounce_query`**         | 2078 | 1297   | **2951** | **6674** |
| `stats_table_frustration_metrics_query`     | 2069 | 644    | 1312     | 3572     |
| `stats_table_entry_bounce_query`            | 193  | 799    | 2331     | 5007     |
| `stats_table_path_bounce_and_avg_time_query`| 1    | 2297   | —        | —        |
| `stats_table_query` (legacy)                | 291  | 943    | 1772     | 6889     |

- **`stats_table_path_bounce_query` is the slow tail.** p95 2.95s, p99 6.67s on
  2.08k queries. Roughly 2× the latency of `main_query` for ~3× fewer queries.
  This is exactly the workload the current branch's lazy-precomputation work
  targets (`adbbff02378`). Worth re-running this query post-rollout to measure
  the win.
- `stats_table_entry_bounce_query` is low volume (193) but p95 2.33s — a
  natural follow-up target for the same lazy treatment, once `path_bounce` lands.
- `stats_table_path_bounce_and_avg_time_query` is essentially unused (1 query
  in 6h). De-prioritize.
- Legacy `stats_table_query` is decaying as old pods rotate — 323 → 296 → 291
  across three sampled windows. Expect it to flatten to near-zero within hours.
- No preaggregated tags showing yet — either the modifier is off in all teams,
  or the preaggregated query type wraps live tags. Check after the lazy rollout.

## Full per-tag picture (last 6h, all web analytics tags)

| query_type                       | cnt  | p95 ms | p99 ms |
| -------------------------------- | ---- | ------ | ------ |
| `web_overview_query`             | 2795 | 1627   | 3911   |
| `web_vitals_path_breakdown_query`| 350  | 539    | 1211   |
| `web_goals_query`                | 278  | **3612** | **8595** |
| `external_clicks_query`          | 12   | 2375   | 2997   |
| `WebAnalyticsPageURLSearch`      | 30   | 205    | 282    |

Plus the stats_table tags above.

**Worst non-stats_table tail: `web_goals_query`** (p95 3.6s, p99 8.6s). 278/6h
volume — small enough that one slow team can move the average, but the tail is
real. Probably the next "single optimization target" outside the path-bounce
work already in flight.

## `NO_COMMON_TYPE` exception text

```
FUNCTION notEquals(
    tupleElement(tuple(mat_$viewport_width, mat_$viewport_height), 1),  -- String
    0                                                                    -- UInt8
) -> notEquals(...) Nullable(UInt8)
```

The query builder is comparing the materialized `$viewport_width` column
(typed `String`) to integer `0`. Affects 3 teams (324931 ×2, 427844 ×1) over
48h. Real bug in stats_table query construction — probably an unconditional
`!= 0` filter that should be `!= ''` (or cast the column to UInt).

`query_id`s for reproduction:

- `324931_7c26c854-5bad-4eb4-a76f-2615864cb0e4_UxkaWLJd` (2026-05-18 13:34)
- `324931_32cf0af9-9b6a-4581-836b-9aec0c4ffb9d_TuE93zEk` (2026-05-18 11:08)
- `427844_26825ef6-4a82-4ecf-9109-a6e5acd7c07b_VqGdN1hS` (2026-05-18 01:52)

## Access method distribution

UI traffic is `access_method=""` (empty), not `"browser"`. Adjust prior
prescriptions in the playbook accordingly.

| access_method      | kind    | cnt  |
| ------------------ | ------- | ---- |
| `""` (UI)          | request | 2798 |
| `personal_api_key` | request | 535  |
| `oauth`            | request | 26   |
| `sharing_token`    | request | 4    |
| `""`               | celery  | 1    |
| `sharing_token`    | celery  | 1    |

## Files in this run

- `q1_tag_dist_6h.tsv` — old hardcoded tag list (incomplete; superseded by q11)
- `q4_errors_24h.tsv` — exception breakdown
- `q6_browser_only_6h.tsv` — empty (taught me UI != `browser`)
- `q7_no_common_type_detail.tsv` — exception text + query_ids
- `q8_access_methods.tsv` — access_method enumeration
- `q9_ext_clicks_sample.tsv` / `q10_ext_full.tsv` — proved `external_clicks_query` is shipping
- `q11_all_stats_tags_6h.tsv` — **the real signal** (per-strategy split)

## Next iteration

Worth tracking:

1. Whether legacy `stats_table_query` count keeps falling (rollout convergence).
2. Whether `stats_table_path_bounce_query` latency moves as the lazy-precomp
   branch lands. Right now it's the worst stats_table tail.
3. Whether any `stats_table_preaggregated*` tag ever fires (today: zero).
