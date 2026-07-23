# Web analytics query serving: the strategy ladder

How a web analytics query gets served: every strategy in the current stack, the order they're tried in, and the exact conditions that route a request down each path.
Source of truth for the code: `products/web_analytics/backend/hogql_queries/`.
For deep precompute internals (schemas, bucketing, insert variants), see [products/web_analytics/PRECOMPUTATION.md](../../products/web_analytics/PRECOMPUTATION.md).

Every strategy tags its ClickHouse queries with a `query_type` that lands in `system.query_log → log_comment.query_type`, so the tag reference at the bottom doubles as a triage tool.

## The serving tiers

Cheapest first.
A request walks down this ladder and stops at the first tier whose conditions it satisfies.

| Tier                                     | What it is                                                                                                                                         | Typical latency |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| 0. Result cache                          | Django/HogQL cached response for the exact query fingerprint                                                                                       | ~ms             |
| 1. Lazy precompute                       | Per-day UTC buckets on the aux cluster, built on demand, TTL-refreshed                                                                             | ~80–200ms       |
| 2. Preaggregated tables (**deprecated**) | Daily preagg tables, modifier-gated; no new enrollments — retained only for the largest existing customers until lazy precompute fully replaces it | ~100ms–1s       |
| 3. Live fast paths                       | Session-id-set (filtered) and no-join (unfiltered) shapes that avoid the full events↔sessions join                                                 | ~1–20s          |
| 4. Full join                             | The original events↔sessions join; always works, slowest                                                                                           | ~5–60s          |

## Request flow

```text
request
  │
  ▼
[0] Django result cache ──hit──▶ return cached (~ms)
  │ miss/stale
  ▼
[1] Lazy precompute gate
  │   enrollment: org flag `web-analytics-precompute-toggle` (or env allowlist);
  │     per-query toggle defaults to opt-out for enrolled teams (#72645) —
  │     only an explicit useWebAnalyticsPrecompute: false rejects
  │   shape: family dispatch (see per-runner tables), no conversion goal,
  │     no sampling, integer timezone, range ≤ 90d, filters events-evaluable
  │     (restricted teams: single exact $host only)
  │   freshness: all day-buckets fresh per TTL band ──▶ serve *_lazy_query (~80–200ms)
  │     expired within 6h SWR grace ──▶ serve stale + enqueue revalidation
  │ miss (NEVER builds inline — enqueues debounced background warm)
  ▼
[2] Preaggregated tables (deprecated)
  │   useWebAnalyticsPreAggregatedTables modifier + supported shape
  │ not enrolled / unsupported
  ▼
[3] Session-id-set fast path (filtered queries)
  │   team on WEB_ANALYTICS_SESSION_ID_SET_TEAM_IDS, filters events-evaluable;
  │   preflight selectivity query first (*_session_id_set_preflight)
  │ unfiltered / not allowlisted / preflight fails
  ▼
[4] No-join fast path (unfiltered queries)
  │   no property filters, no conversion goal, no session-table fields;
  │   WEB_ANALYTICS_NO_JOIN_TEAM_IDS + rollout % (100% on Cloud)
  │ needs session fields with filters
  ▼
[5] Full events↔sessions join (unconditional fallback)
```

**The one-way rule (#72959):** user-facing reads never build precompute buckets inline — `run_inserts` is true only for background-warming requests.
A miss costs one live-path serve; the background warm makes the next identical request a bucket hit.
The dashboard "enqueues precompute" as a side effect; it never waits on it.

## Per-runner dispatch

### WebOverviewQuery (`web_overview.py`)

| #   | Strategy                   | Conditions                                                           | Tag                                 |
| --- | -------------------------- | -------------------------------------------------------------------- | ----------------------------------- |
| 1   | Lazy precompute            | Shared gate only — overview has no extra shape restrictions          | `web_overview_lazy_query`           |
| 2   | Preaggregated (deprecated) | Modifier on + no conversion goal                                     | `web_overview_preaggregated_query`  |
| 3   | Session-id-set             | Filtered + allowlisted + preflight passes (sets `sessionIdPushdown`) | `web_overview_session_id_set_query` |
| 4   | No-join                    | Unfiltered, no conversion goal                                       | `web_overview_no_join_query`        |
| 5   | Full join                  | Fallback                                                             | `web_overview_query`                |

### WebStatsTableQuery (`stats_table.py`) — three lazy families, tried in order

| #   | Strategy                   | Conditions                                                                                                                                                                                                                     | Tag                                                                                                                  |
| --- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| 1   | Paths lazy                 | `breakdownBy` ∈ {Page, InitialPage} + `includeBounceRate`; rejects avg-time-on-page, scroll depth, unsupported orderBy; top-K 10,000 paths/day cap for high-cardinality teams                                                  | `web_stats_paths_lazy_query`                                                                                         |
| 2   | Frustration lazy           | `breakdownBy` = FrustrationMetrics; rejects unsupported orderBy                                                                                                                                                                | `web_stats_frustration_lazy_query`                                                                                   |
| 3   | Simple-breakdown lazy      | ~18 supported breakdowns (DeviceType, Browser, OS, Country, Region, City, Viewport, Timezone, Language, ExitPage, InitialChannelType, InitialReferringDomain/URL, InitialUTM\_\*); rejects bounce rate, avg time, scroll depth | `web_stats_lazy_query`                                                                                               |
| 4   | Preaggregated (deprecated) | Modifier on + no avg-time-on-page + no conversion goal                                                                                                                                                                         | `stats_table_preaggregated*`                                                                                         |
| 5   | Session-id-set             | Page breakdown ± avg time, filtered + allowlisted + preflight                                                                                                                                                                  | `stats_table_session_id_set_path_bounce[_and_avg_time]`                                                              |
| 6   | No-join                    | Unfiltered: path-bounce, path-bounce+avg-time, or simple breakdown without session fields                                                                                                                                      | `stats_table_no_join_*`                                                                                              |
| 7   | Full join                  | Fallback per shape                                                                                                                                                                                                             | `stats_table_path_bounce`, `stats_table_entry_bounce`, `stats_table_channel_type`, `stats_table_simple_breakdown`, … |

### Goals, vitals, external clicks

| Runner                      | Tier 1                        | Fallback                                 | Notes                                                         |
| --------------------------- | ----------------------------- | ---------------------------------------- | ------------------------------------------------------------- |
| WebGoalsQuery               | Lazy (`web_goals_lazy_query`) | Live (`web_goals_query`)                 | Needs actions configured; no fast-path shapes exist           |
| WebVitalsPathBreakdownQuery | Lazy                          | Live (`web_vitals_path_breakdown_query`) | Requires day-aligned range; exempt from integer-timezone gate |
| WebExternalClicksTableQuery | —                             | Live (`external_clicks_query`)           | Live-only; no precompute family                               |

## Lazy precompute freshness (summary)

Full details in [PRECOMPUTATION.md](../../products/web_analytics/PRECOMPUTATION.md); the operative numbers:

| Day age        | TTL    |
| -------------- | ------ |
| Today (0d)     | 4h     |
| Yesterday (1d) | 6h     |
| 2–7d           | 5d     |
| 8–14d          | 7d     |
| 15–21d         | 10d    |
| 22–35d         | 12–14d |
| 36d+           | 21d    |

- Stale-while-revalidate: 6h grace; user reads inside it get the stale row instantly (tagged `precompute_stale=true`) with a Celery revalidation enqueued (10-min debounce). Background warmers are never served stale — they are the refresh.
- Session settling: 24h forward pad on event scans, matching the SDK session length cap.
- OOM protection: a team that OOMs during a build gets Redis-pinned for 14 days to 1-day insert windows.
- Max range: 90 days; wider requests are permanently live.

## Background warming systems

Three writers keep buckets warm; user reads only ever consume.

| System                                             | Trigger tag                     | When                  | What it does                                                                                                                                                                              |
| -------------------------------------------------- | ------------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hourly demand warmer (Dagster, `cache_warming.py`) | `webAnalyticsQueryWarming`      | Hourly                | Selects hot shapes from query_log (kind `Web%`, ≥2 hits in 2 days; raw-path shapes keep a ≥10 bar), expands sub-30d ranges to −30d, replays via an 8-worker pool with the opt-in injected |
| Warm-behind on miss                                | (background warming request)    | On any user-read miss | Debounced rebuild of exactly the shape that missed; self-heals first-hit misses in ~30–60s                                                                                                |
| Stale revalidation                                 | `webAnalyticsStaleRevalidation` | On stale-grace serves | Refreshes expired buckets after serving the stale copy                                                                                                                                    |

## Flags and team allowlists

| Gate                                                  | Type             | Controls                                                                                                        |
| ----------------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------- |
| `web-analytics-precompute-toggle`                     | Org feature flag | Lazy precompute enrollment; enrolled teams read by default (opt-out). Evaluated locally, fails closed           |
| `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS`              | Env allowlist    | Flag-independent precompute enrollment (shared with Dagster warmers, where flag evaluation is unreliable)       |
| `WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS` | Env allowlist    | Lifts the single-`$host` filter-shape restriction — any filter combo becomes precomputable (own cache key each) |
| `WEB_ANALYTICS_SESSION_ID_SET_TEAM_IDS`               | Env allowlist    | Filtered fast path (live tier)                                                                                  |
| `WEB_ANALYTICS_NO_JOIN_TEAM_IDS` + rollout %          | Env + percentage | Unfiltered fast path — 100% on Cloud                                                                            |
| `useWebAnalyticsPrecompute`                           | Per-query field  | User opt-out switch (WebAnalyticsMenu toggle); explicit `false` always wins                                     |
| `useWebAnalyticsPreAggregatedTables`                  | Query modifier   | Preaggregated-tables tier (deprecated — largest existing customers only, no new enrollments)                    |

## query_type tag reference

Suffix conventions: `*_lazy_query` = bucket read (served from precompute), `*_lazy_insert` = bucket build (background only), `*_preflight` = selectivity probe.

| Family          | Precompute                                                                                                 | Live tags                                                                                                                                                                                                                                    |
| --------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Overview        | `web_overview_lazy_query/insert`, `web_overview_preaggregated_query`                                       | `web_overview_no_join_query`, `web_overview_session_id_set_query` (+`_preflight`), `web_overview_query`                                                                                                                                      |
| Stats table     | `web_stats_paths_lazy_*`, `web_stats_frustration_lazy_*`, `web_stats_lazy_*`, `stats_table_preaggregated*` | `stats_table_no_join_*`, `stats_table_session_id_set_*` (+`_preflight`), `stats_table_path_bounce[_and_avg_time]`, `stats_table_entry_bounce`, `stats_table_channel_type`, `stats_table_frustration_metrics`, `stats_table_simple_breakdown` |
| Goals           | `web_goals_lazy_query/insert`                                                                              | `web_goals_query`                                                                                                                                                                                                                            |
| Vitals          | `web_vitals_paths_lazy_insert`                                                                             | `web_vitals_path_breakdown_query`                                                                                                                                                                                                            |
| External clicks | —                                                                                                          | `external_clicks_query`                                                                                                                                                                                                                      |

## Reading a slow tile

Find the request in query_log and check `query_type`.
A `*_lazy_query` taking seconds is a bucket-read problem (rare).
A fast-path or full-join tag on an enrolled team means the lazy gate rejected the query (filters, avg-time-on-page, >90d range, opt-out) or the buckets weren't fresh — in which case a background warm is already in flight and the next identical request should hit.
