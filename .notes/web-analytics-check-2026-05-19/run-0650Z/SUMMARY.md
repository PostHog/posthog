# Web analytics snapshot — 2026-05-19 06:50 UTC (run-0650Z)

Diff vs run-0617Z. 24h focus on the path_bounce slow-cluster pattern.

## Path bounce slow pattern (24h, 30-min buckets)

`q17_pathbounce_30m_24h.tsv` covers 20:30 → 06:30. Big slow buckets:

| Bucket (UTC)        | over_10s | between_5_10s | total | p95 ms |
| ------------------- | -------- | ------------- | ----- | ------ |
| 2026-05-18 21:00    | 1        | 2             | 190   | 2251   |
| 2026-05-18 23:30    | 1        | 4             | 220   | 2352   |
| 2026-05-19 00:30    | 0        | 4             | 202   | 3432   |
| **2026-05-19 02:00**| **3**    | **5**         | 141   | **5485** |
| 2026-05-19 03:30    | 0        | 4             | 130   | 4136   |
| **2026-05-19 04:00**| **3**    | **5**         | 138   | **5391** |
| 2026-05-19 06:00    | 0        | 0             | 173   | 1530   |
| 2026-05-19 06:30    | 0        | 0             | 125   | 1524   |

The 02:00 and 04:00 peaks are real and almost identically shaped (3 over-10s,
5 between-5–10s, similar p95). Spaced exactly 2 hours apart, but the
hypothetical 06:00 third peak **did not appear** for the third hour in a row
now — so the pattern is not strictly 2-hourly across the full day.

### Not the cache warmer

`q19_cache_warmer_path_bounce.tsv` slices by `feature` and `trigger`. Cache
warmer (`feature=cache_warmup`, `trigger=warmingV2`) emits 1–3 queries per
bucket and never appears in slow buckets — its own p95s are 1.4–2.7s.

The slow buckets are dominated by regular `feature=query`, empty
`access_method` (= UI traffic). So the spikes are **real user dashboards**,
not scheduled jobs.

### Personal API key noise

Worth noting separately: at 00:00 bucket, 7 `personal_api_key` queries with
**p95 7334ms** — one heavy poller again (likely team 125691 from prior
slices). These spikes are isolated to specific API consumers and don't
affect the UI numbers.

## `web_goals_query` 12h trend (30-min buckets)

`q18_goals_30m_12h.tsv` shows the same kind of bucket spikes:

| Bucket    | cnt | p95 ms |
| --------- | --- | ------ |
| 21:00     | 22  | 3572   |
| 23:30     | 28  | 5587   |
| **01:00** | 13  | **8754** |
| **02:00** | 19  | **6553** |
| 04:00     | 29  | 4832   |

Same 02:00, 04:00 alignment with path_bounce. **The slow clusters are
cross-tag** — a coordinated event hits both path_bounce and goals (and
probably entry_bounce) at the same wall-clock times. Strongly suggests a
shared underlying cause: a small population of dashboards with synchronized
auto-refresh.

Current state (06:00–06:30): both tags calm. Whatever cohort is firing at
02:00 and 04:00 has wound down.

## Per-tag 6h numbers (vs 30 min ago)

| Tag                                     | cnt now | cnt prior | p95 now | p95 prior |
| --------------------------------------- | ------- | --------- | ------- | --------- |
| `stats_table_main_query`                | 6207    | 6223      | 1514    | 1527      |
| `web_overview_query`                    | 2542    | 2558      | 1729    | 1731      |
| `stats_table_path_bounce_query`         | 1960    | 1962      | 2890    | 2941      |
| `stats_table_frustration_metrics_query` | 1952    | 1960      | 1293    | 1362      |
| `web_vitals_path_breakdown_query`       | 366     | 347       | 481     | 495       |
| `web_goals_query`                       | 320     | 298       | 2726    | 2907      |
| `stats_table_query` (legacy)            | 191     | 220       | 1815    | 1832      |
| `stats_table_entry_bounce_query`        | 190     | 174       | 2320    | 2329      |
| `external_clicks_query`                 | 127     | 94        | 2421    | 2701      |

The downward drift on `web_goals_query` and `external_clicks_query` p95s
across iterations is mostly **window-sliding effect**: the 6h window has been
moving forward in 30-min steps, and the slow 23:30, 00:30, 01:00 buckets are
gradually exiting the window while the calm 06:00–06:30 buckets are entering.
Not a real improvement — just rotating window content.

## Files

- `q11b_all_web_tags_6h.tsv` — per-tag aggregate
- `q17_pathbounce_30m_24h.tsv` — 30-min × 24h slow-bucket pattern
- `q18_goals_30m_12h.tsv` — goals trend confirming cross-tag alignment
- `q19_cache_warmer_path_bounce.tsv` — eliminated cache warmer hypothesis

## Watch list for next iteration

1. Identify the team cohort hitting 02:00 and 04:00 windows — single
   `team_id` query on slow bucket queries would do it. If it's a small set,
   they're the obvious lazy-precomp canary candidates.
2. Whether the next "scheduled-feeling" slow cluster appears (08:00?
   pattern unclear).
