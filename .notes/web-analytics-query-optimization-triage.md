# Web Analytics — ClickHouse/HogQL query optimization triage

Date: 2026-06-09
Method: `/optimizing-clickhouse-and-hogql-queries` skill, full-team pass, prioritized by real
production cost (`posthog.query_log_archive`, US, 7 days) and measured on the Test Cluster (team 2).

## Scope

Owner: `@PostHog/team-web-analytics` (soft-owned only — never blocks a PR).
Inventory: ~42 backend query sites + ~36 frontend sites across `products/web_analytics`,
`posthog/hogql_queries/web_analytics`, `products/marketing_analytics`, heatmaps, and the
web-analytics frontend scenes. Both backend and frontend idioms were searched.

### Stale CODEOWNERS-soft entries (flagged, not silently substituted)

| Line | Stale entry                                        | Moved to                                                     |
| ---- | -------------------------------------------------- | ------------------------------------------------------------ |
| 58   | `posthog/models/heatmap_saved.py`                  | `products/web_analytics/backend/models/heatmap_saved.py`     |
| 60   | `posthog/tasks/heatmap_screenshot.py`              | `products/web_analytics/backend/tasks/heatmap_screenshot.py` |
| 63   | `nodejs/.../event-pipeline-runner-heatmap-step.ts` | refactored into `check-heatmap-opt-in-step.ts`               |

## How WA queries are tagged in query_log

Base runner `WebAnalyticsQueryRunner` tags every query `lc_product='web_analytics'` and a specific
`lc_query_type` (e.g. `web_overview_query`, `stats_table_path_bounce_query`). `query_log_archive`
is a `Distributed` table over the `ops` cluster (typed `lc_*` columns, ~22d retention) — query it
directly, no `clusterAllReplicas`.

## Production cost ranking (7d, US, by read_bytes)

Two distinct cost stories emerged.

### Story 1 — user-facing latency (ONLINE live runners)

| query_type                            | queries | total_read | avg_ms   | p95_ms   | slow>30s | teams  | bytes/query |
| ------------------------------------- | ------- | ---------- | -------- | -------- | -------- | ------ | ----------- |
| web_overview_query                    | 104,554 | 56.5 TiB   | 658      | 1313     | 62       | 35,798 | ~540 MB     |
| web_goals_query                       | 12,254  | 52.9 TiB   | 988      | 2337     | 4        | 4,307  | ~4.3 GB     |
| stats_table_simple_breakdown_query    | 206,495 | 46.9 TiB   | 570      | 1072     | 45       | 35,657 | ~227 MB     |
| **stats_table_path_bounce_query**     | 58,396  | 36.9 TiB   | **1146** | **2529** | **53**   | 12,612 | **~632 MB** |
| stats_table_channel_type_query        | 42,401  | 30.8 TiB   | 731      | 1534     | 10       | 11,347 | ~745 MB     |
| stats_table_frustration_metrics_query | 60,298  | 10.4 TiB   | 565      | 1194     | 18       | 12,672 | ~177 MB     |
| calendar_heatmap_query                | 62,277  | 7.5 TiB    | 364      | 756      | 13       | 12,975 | ~123 MB     |

Generic insight queries embedded in WA dashboards (also real cost, but generic runners, not WA code):
`RetentionQuery` 108 TiB / 12,789 teams, `TrendsQuery` 42 TiB / 13,290 teams.

### Story 2 — background bytes (team_id=0 jobs, empty query_type)

- `raw_sessions_v3` **backfill**: 27.3 PiB, avg 18 min/query — transient migration, will end. Flag, don't optimize.
- `web_pre_aggregated_bounces_staging` **preaggregation** inserts: 607 TiB — the existing v2 precompute write path.
- health-check `SELECT team_id FROM events ... GROUP BY team_id`: 36.9 TiB across 2 normalized shapes,
  avg 6 s, ~7.8k runs/wk. Multi-team (HogQL-exempt); optimize in place if at all.

## Measured deep-dive: `stats_table_path_bounce_query` (the one true query-level target)

It is the **only** tier-1 live query with a structural **self-join**. Confirmed in the prod SQL:
`counts LEFT JOIN bounce ON breakdown_value`, where both subqueries independently scan `events`,
join `raw_sessions` + `person_distinct_id_overrides`, and recompute the giant `$channel_type`
dictionary expression. (web*overview and web_goals are already single-pass — their fix is precompute,
not a rewrite. Materialization is healthy in prod: `mat*$pathname`, `mat_$host`, etc., so the
`JSONExtract` smell in snapshots is a test-only artifact.)

Source: `products/web_analytics/backend/hogql_queries/query_constants/stats_table_queries.py`
(`PATH_BOUNCE_QUERY`, `PATH_BOUNCE_AND_AVG_TIME_QUERY`).

### Measurement (Test Cluster, team 2, 1 week of March, median of 5 runs)

| metric                          | CURRENT (2-scan) | CANDIDATE (1-scan) | delta                                   |
| ------------------------------- | ---------------- | ------------------ | --------------------------------------- |
| read_rows                       | 60,650,624       | 30,324,744         | **−50.0% (exact 2.00×, deterministic)** |
| read_bytes                      | 6.26 GiB         | 4.78 GiB           | −24%                                    |
| query_duration_ms (median of 5) | 4825 ms          | 3130 ms            | **−35% (1.54× faster)**                 |
| peak memory                     | 4.94 GiB         | 4.00 GiB           | −19%                                    |

Result correctness: `n_paths` identical (903,468), `views` identical (3,836,834), `visitors` within
8/765k (`any()` nondeterminism). **BUT `avg_bounce` diverged 0.0677 → 0.0856.**

> Caveat: a small window + the cluster's ~32.6 GiB per-query memory cap forced this measurement onto a
> 1-week slice (the high-cardinality `GROUP BY (session_id, pathname)` + the raw_sessions hash join OOM
> a 4-month window). The `read_rows` halving is deterministic and window-independent; duration is the
> median of 5.

### The catch — and the fix (both measured)

The _naive_ single-pass collapse (group by event pathname, attribute bounce only when the pathname is the
session's entry path) **changes bounce-rate semantics** — it shifted bounce 0.068→0.086 (~26%) on team 2.
Do not ship it.

The _correct_ single-pass keeps both grains over one scan via **per-session `arrayJoin` fan-out** (the same
pattern `web_goals_lazy_precompute` already uses): one events+sessions scan → GROUP BY session →
fan out one "view" row per viewed pathname + one "bounce" row at the entry pathname → final GROUP BY
breakdown_value with conditional aggregation. Bounce is attributed exactly once per session at its entry
pathname, matching the original.

Consolidated measurement (Test Cluster, team 2, 1-week March slice, median of 5):

| variant                   | median_ms | read_rows  | read_bytes   | peak_mem     | bounce     | correct  |
| ------------------------- | --------- | ---------- | ------------ | ------------ | ---------- | -------- |
| CURRENT (2-scan baseline) | 4825      | 60,650,624 | 6.26 GiB     | 4.98 GiB     | 0.0677     | baseline |
| naive 1-scan              | 3130      | 30,324,744 | 4.78 GiB     | 4.14 GiB     | 0.0856     | ❌       |
| arrayJoin 1-scan          | 3159      | 30,324,744 | 4.78 GiB     | 4.18 GiB     | 0.0691     | ✅       |
| **bounce-from-sessions**  | **2693**  | 35,663,429 | **3.80 GiB** | **3.27 GiB** | **0.0676** | ✅✅     |

**Winner: run the bounce half from the `sessions` table, keep counts on events.** vs baseline:
**−44% latency (1.79×), −39% read_bytes, −34% memory**, and the most faithful result (bounce 0.0676 vs
0.0677, n_paths + views exact). The bounce side needs **zero events** — `$entry_pathname` and `$is_bounce`
are pure session attributes, so the current query's second pageview-events scan is pure waste. Cheaper in
bytes than the arrayJoin (3.80 vs 4.78 GiB) despite more rows, because it reads ~122 MiB of session columns
instead of a second events pass, and the counts-side session join carries only `start_ts`. Also the
simplest: the bounce subquery becomes `SELECT $entry_pathname, avgIf($is_bounce, …) FROM sessions GROUP BY
$entry_pathname` — no arrayJoin, no groupArray memory risk.

Caveat — this is a **conditional** optimization, sized against prod (7d, path_bounce queries):

| bounce side           | share of queries | teams | path                                     |
| --------------------- | ---------------- | ----- | ---------------------------------------- |
| no event-level filter | **67%** (39,634) | ~11k  | sessions-bounce (the −44% win)           |
| event-level filter    | **33%** (19,487) | ~3.6k | keep current events-join (no regression) |

`raw_sessions` exposes a rich initial*\* set (browser, os, device_type, geoip country/subdivision/city,
viewport, referring_domain, all UTMs + click IDs, entry_url, end_url), so most WA filters (Browser, OS,
Device, Country, Region, City, Viewport, Referrer, UTM, channel) are session-expressible. The genuinely
not-on-sessions filters are person props and `$host`/`$ip`/custom event props — and sampling the 33%
shows it is dominated by the **default test-accounts filter** (`mat_pp_email` + `mat*$host` + `mat_$ip`),
which cannot move to sessions. So: apply sessions-bounce when the bounce side has no event-level filter
(≈67% of queries, the clean win); fall back to today's events-join otherwise (no regression). A session
semijoin (`sessions WHERE session_id IN (SELECT session_id FROM events WHERE <event filter>)`) is a possible
future refinement for the 33% but was not measured.

### Option 2 (dedupe the session subquery) is a dead end

Decomposition: the `raw_sessions` scan is only **122 MiB / 5.34M rows — ~2% of the 6.26 GiB**. The cost is
the **duplicate events scan**, not raw_sessions. And ClickHouse inlines CTEs, so a session subquery
referenced by two event-side joins executes twice regardless; you cannot compute it once without a
materialized intermediate. For the common _unfiltered_ query there is also no `$channel_type` to dedupe.
So the safe win is the correct single events scan (arrayJoin), not session-subquery dedup.

## Recommendations (by priority and layer)

1. **Route path-bounce (and the other breakdowns) through precompute — the real lever.** The team's
   pre-aggregation work is the correct fix for the high-breadth live queries. The data shows it's still
   early (most `*_lazy_insert` / `*_dimensional_insert` types serve a single dogfooding team). Prioritizing
   broad rollout of `stats_table_preaggregated_*` retires the live-path self-join entirely. **Layer: query
   runner routing + precompute coverage.**
2. **Safe in-place win for the live path while precompute rolls out: move the bounce half of
   `PATH_BOUNCE_QUERY` onto the `sessions` table** (measured **−44% latency, −39% bytes, −34% memory**, most
   faithful result). The bounce side currently scans pageview events purely to re-derive `$is_bounce` — a
   session-level fact — so replace it with `SELECT $entry_pathname, avgIf($is_bounce, …) FROM sessions GROUP
BY $entry_pathname`; keep the counts half on events (per-page views/visitors aren't in `sessions`).
   Single-team → HogQL is the right layer:
   `products/web_analytics/backend/hogql_queries/query_constants/stats_table_queries.py`; same idea retires
   one of the scans in the 3-scan `PATH_BOUNCE_AND_AVG_TIME_QUERY`. Snapshot the new `.ambr` and assert the
   reduced scan count. Apply conditionally: fall back to the events-join (or a session semijoin) when there
   are event-level property filters not present on the session. The `arrayJoin` single-scan is a viable
   alternative but is slower, heavier, and more complex than bounce-from-sessions. NOTE: "dedupe the session
   subquery only" is a dead end — `raw_sessions` is ~2% of the read and CTE inlining blocks it.
3. **Do not ship the naive event-grain single-pass** (group-by-pathname + is_entry collapse) — it changes
   bounce attribution (~26% on team 2). Use the arrayJoin form, which preserves it.
4. **Lower priority:** health-check `SELECT team_id FROM events` scans (36.9 TiB/wk, multi-team, HogQL-exempt)
   — only worth tuning if the cross-team scan cost matters; consider a narrower window or pre-aggregated source.

## Reproduction

- Cost ranking: `hogli metabase:query --region us --database-id 143` (ONLINE) against
  `posthog.query_log_archive`, filter `lc_product='web_analytics'`, group by `lc_query_type`, `lc_workload`.
- Measurement: `/tmp/wa_current.sql` vs `/tmp/wa_candidate.sql` on `--database-id 146` (Test Cluster, team 2),
  markers `wa_measure_current_v3` / `wa_measure_candidate_v3`; pull `read_rows`/`read_bytes`/`query_duration_ms`
  from that cluster's `system.query_log`.
