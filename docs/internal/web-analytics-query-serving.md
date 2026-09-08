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
| 1. Lazy precompute                       | Hourly UTC buckets (vitals: team-tz daily) on the aux cluster, built by background daily-UTC jobs, TTL-refreshed                                   | ~80–200ms       |
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
  │     no sampling, integer timezone, `sessionsV2JoinMode` ≠ uuid,
  │     range ≤ 90d, filters events-evaluable
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
  │   team on WEB_ANALYTICS_SESSION_ID_SET_TEAM_IDS or the
  │     `web-analytics-session-id-set` rollout flag, filters events-evaluable;
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

| Runner                      | Tier 1                              | Fallback                                 | Notes                                                                          |
| --------------------------- | ----------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------ |
| WebGoalsQuery               | Lazy (`web_goals_lazy_query`)       | Live (`web_goals_query`)                 | Needs actions configured; no fast-path shapes exist                            |
| WebVitalsPathBreakdownQuery | Lazy                                | Live (`web_vitals_path_breakdown_query`) | Requires day-aligned range; exempt from integer-timezone gate                  |
| WebExternalClicksTableQuery | —                                   | Live (`external_clicks_query`)           | Live-only; no precompute family                                                |
| WebBotsTableQuery           | Lazy (`web_bots_lazy_query`)        | Live (`web_bots_query`)                  | Crawlers and Most crawled paths; see [Bot analytics](#bot-analytics)           |
| Bot request trend chart     | Lazy (`web_bots_trends_lazy_query`) | Live trends                              | A `TrendsQuery` on `WebTrendsQueryRunner`; see [Bot analytics](#bot-analytics) |

## Lazy precompute freshness (summary)

### Bot analytics

Every tile on the AI/Search bots view reads `posthog.web_bots_preaggregated`.
The table stores, for each UTC hour, the request count and the most recent request time per crawler, category, host, and path.
One job set therefore serves the Crawlers table, the Most crawled paths table, and all four tabs of the request trend chart.
Counts cover `$pageview`, `$screen`, and `$http_log`.

Reads combine stored hours with live events for everything the stored hours do not cover.
That is the two partial-hour boundaries of the requested range, and any hour after the job ran.
A job for a window that has not elapsed yet holds no rows past its own `computed_at`, so a read that trusted the whole window would report those hours as zero.
Exact date filters, request times, and the recent end of a chart are all preserved this way.

The job identity includes the compiled bot classification: the built-in definitions, the bot IP ranges, and the project's custom bot rules.
A change to any of them mints new jobs, so stored rows never outlive the classification that produced them.
User filters and test-account filters are part of the job identity too.

#### Tables

`WebBotsTableQuery` serves the Crawlers and Most crawled paths tables.
The shared precompute enrollment and the per-query "Allow precompute" opt-out both apply.
Comparison ranges stay on the live query.
Query types: `web_bots_lazy_insert`, `web_bots_lazy_query`, `web_bots_query`.

#### Request trend chart

The chart is a `TrendsQuery` that the bots tab tags with `productKey: web_analytics`, so it dispatches to `WebTrendsQueryRunner`.
That runner tries the bot buckets before the overview buckets, because the overview buckets carry none of the four breakdown dimensions.
Read rows go through the live trends runner's own `build_series_response`, so labels, the "Other" bucket, series order, and the response contract come from the live path rather than a second implementation of it.
Ranking mirrors the live outer query: rank on (ordering, total descending, value ascending), keep the top 25, and fold the rest into one "Other" row.

Enrollment is the `web-analytics-trends-precompute` flag at dispatch plus the shared precompute enrollment inside the gate; both are folded into the runner's cache key, so turning either off is an immediate kill switch.
`TrendsQuery` carries no `useWebAnalyticsPrecompute` field, so the per-query opt-out cannot reach a trend tile.

Only the bots tab's own chart shape is admitted.
These stay on the live path: any other breakdown property, multiple breakdowns, a breakdown limit, URL normalization or path cleaning, a comparison range, a series that is not the three bot events OR-ed into one total, formulas, a non-line display, an interval other than hour, day, week, or month, an explicit date range, and an hour-interval range that crosses a DST transition.
Query type: `web_bots_trends_lazy_query`.

#### Out of scope

Agent journey analytics and citation tracking keep their existing paths.

#### Rollout

Land the ClickHouse table migration in its own migration-only pull request and deploy it before the application changes.
Then check result parity, precompute use, query duration, and the `web_bots_trends_lazy_precompute_fallback` reasons before expanding enrollment.

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

Four writers keep buckets warm; user reads only ever consume.

| System                                                               | Trigger tag                        | When                  | What it does                                                                                                                                                                              |
| -------------------------------------------------------------------- | ---------------------------------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Eager baseline warmer (Dagster, `eager_web_analytics_precompute.py`) | `webAnalyticsEagerBaselineWarming` | Hourly at :05         | Pre-warms the fixed dashboard matrix (overview, goals, vitals, one stats query per breakdown) over a trailing 28d window for flag-enrolled teams (cap 200, 45-min cycle budget)           |
| Hourly demand warmer (Dagster, `cache_warming.py`)                   | `webAnalyticsQueryWarming`         | Hourly                | Selects hot shapes from query_log (kind `Web%`, ≥2 hits in 2 days; raw-path shapes keep a ≥10 bar), expands sub-30d ranges to −30d, replays via an 8-worker pool with the opt-in injected |
| Warm-behind on miss                                                  | (background warming request)       | On any user-read miss | Debounced rebuild of exactly the shape that missed; self-heals first-hit misses in ~30–60s                                                                                                |
| Stale revalidation                                                   | `webAnalyticsStaleRevalidation`    | On stale-grace serves | Refreshes expired buckets after serving the stale copy                                                                                                                                    |

## Flags and team allowlists

| Gate                                                  | Type              | Controls                                                                                                        |
| ----------------------------------------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------- |
| `web-analytics-precompute-toggle`                     | Org feature flag  | Lazy precompute enrollment; enrolled teams read by default (opt-out). Evaluated locally, fails closed           |
| `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS`              | Env allowlist     | Flag-independent precompute enrollment (shared with Dagster warmers, where flag evaluation is unreliable)       |
| `WEB_ANALYTICS_LAZY_PRECOMPUTE_UNRESTRICTED_TEAM_IDS` | Env allowlist     | Lifts the single-`$host` filter-shape restriction — any filter combo becomes precomputable (own cache key each) |
| `WEB_ANALYTICS_SESSION_ID_SET_TEAM_IDS`               | Env allowlist     | Filtered fast path (live tier)                                                                                  |
| `web-analytics-session-id-set`                        | Team rollout flag | Filtered fast path enrollment without the env allowlist — either gate admits the team                           |
| `WEB_ANALYTICS_NO_JOIN_TEAM_IDS` + rollout %          | Env + percentage  | Unfiltered fast path — 100% on Cloud                                                                            |
| `useWebAnalyticsPrecompute`                           | Per-query field   | User opt-out switch (WebAnalyticsMenu toggle); explicit `false` always wins                                     |
| `useWebAnalyticsPreAggregatedTables`                  | Query modifier    | Preaggregated-tables tier (deprecated — largest existing customers only, no new enrollments)                    |

## query_type tag reference

Suffix conventions: `*_lazy_query` = bucket read (served from precompute), `*_lazy_insert` = bucket build (background only), `*_preflight` = selectivity probe.

| Family          | Precompute                                                                                                 | Live tags                                                                                                                                                                                                                                    |
| --------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Overview        | `web_overview_lazy_query/insert`, `web_overview_preaggregated_query`                                       | `web_overview_no_join_query`, `web_overview_session_id_set_query` (+`_preflight`), `web_overview_query`                                                                                                                                      |
| Stats table     | `web_stats_paths_lazy_*`, `web_stats_frustration_lazy_*`, `web_stats_lazy_*`, `stats_table_preaggregated*` | `stats_table_no_join_*`, `stats_table_session_id_set_*` (+`_preflight`), `stats_table_path_bounce[_and_avg_time]`, `stats_table_entry_bounce`, `stats_table_channel_type`, `stats_table_frustration_metrics`, `stats_table_simple_breakdown` |
| Goals           | `web_goals_lazy_query/insert`                                                                              | `web_goals_query`                                                                                                                                                                                                                            |
| Vitals          | `web_vitals_paths_lazy_query/insert`                                                                       | `web_vitals_path_breakdown_query`                                                                                                                                                                                                            |
| External clicks | —                                                                                                          | `external_clicks_query`                                                                                                                                                                                                                      |
| Bot analytics   | `web_bots_lazy_query/insert`, `web_bots_trends_lazy_query`                                                 | `web_bots_query`, the live trends tags                                                                                                                                                                                                       |

## Reading a slow tile

Find the request in query_log and check `query_type`.
A `*_lazy_query` taking seconds is a bucket-read problem (rare).
A fast-path or full-join tag on an enrolled team means the lazy gate rejected the query (filters, avg-time-on-page, >90d range, opt-out) or the buckets weren't fresh — in which case a background warm is already in flight and the next identical request should hit.
