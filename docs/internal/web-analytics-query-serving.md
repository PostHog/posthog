# Web analytics query serving: the strategy ladder

How a web analytics query gets served: every strategy in the current stack, the order they're tried in, and the exact conditions that route a request down each path.
Source of truth for the code: `products/web_analytics/backend/hogql_queries/`.
For deep precompute internals (schemas, bucketing, insert variants), see [products/web_analytics/PRECOMPUTATION.md](../../products/web_analytics/PRECOMPUTATION.md).

Every strategy tags its ClickHouse queries with a `query_type` that lands in `system.query_log → log_comment.query_type`, so the tag reference at the bottom doubles as a triage tool.

## The serving tiers

Historical heatmaps use a separate replay analysis path, described below.
They do not use these web analytics query caches.

Cheapest first.
A request walks down this ladder and stops at the first tier whose conditions it satisfies.

| Tier                                     | What it is                                                                                                                                         | Typical latency |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| 0. Result cache                          | Django/HogQL cached response for the exact query fingerprint                                                                                       | ~ms             |
| 1. Lazy precompute                       | Hourly UTC buckets (vitals: team-tz daily) on the aux cluster, built by background daily-UTC jobs, TTL-refreshed                                   | ~80–200ms       |
| 2. Preaggregated tables (**deprecated**) | Daily preagg tables, modifier-gated; no new enrollments — retained only for the largest existing customers until lazy precompute fully replaces it | ~100ms–1s       |
| 3. Live fast paths                       | Session-id-set (filtered) and no-join (unfiltered) shapes that avoid the full events↔sessions join                                                 | ~1–20s          |
| 4. Full join                             | The original events↔sessions join; always works, slowest                                                                                           | ~5–60s          |

## Historical heatmaps

The `heatmaps-historical-variants` flag enables the historical view for projects with Session replay enabled.
The historical view shows a gallery ordered by when each variant was first observed.
Hover a variant or focus it with the keyboard to preview its click heatmap over the thumbnail.
Hover a heatmap hotspot in either view to see the sum of recorded clicks within 24 page pixels of the pointer, adjusted for screenshot scale.
Select a thumbnail to inspect its full-page heatmap; Previous and Next move between variants without leaving the viewer.
Dates and screen width stay visible, while the Filters button expands cohort, event, and internal-traffic controls and shows the number of active filters.
Results are saved automatically and shared with Copy link; screenshot selection and View recording are inside the variant viewer.
About this data contains reconstruction limits and detailed coverage counts.
Sampled results and missing recordings remain visible in the gallery, and changed filters require Update results before they affect it.
An editor starts an analysis from a saved heatmap with an exact URL, an absolute date range of at most 90 days, a screen width, and optional existing cohort, event, and internal-traffic filters.
Dates use an inclusive start and exclusive end; date-only selections include the entire final day in the project timezone.
An analysis has a stable ID in the page URL that teammates can open with heatmap and replay access.
Changing filters does not change a saved result: the UI marks the filters as changed and starts a new analysis only when requested.

`POST /api/projects/{project_id}/heatmap_analyses/` enqueues `analyze_heatmap` on the existing exports queue.
The worker uses the existing recording listing query, rendering service (`BROWSERLESS_CDP_URL` and `BROWSERLESS_TOKEN`), and authenticated replay exporter.
It looks for recordings in 20 time buckets, deduplicates session IDs, and checks recorded page URL, tab, timestamp, and viewport during reconstruction.
Clicks come from rrweb interaction events, with replay scroll offsets applied to document coordinates.
The combined heatmap continues to use all captured heatmap traffic; historical variants represent only the analyzed replay sample.
Visits can encounter more than one variant, so variant visit counts are not mutually exclusive.

The renderer samples page states and groups compatible geometry and recorded content.
Changed promotional images, headings, or page text separate variants even when the layout has the same dimensions.
Each variant chooses a representative from a bounded medoid sample and offers alternative recorded moments.
The worker persists membership and the selected representative so source expiry does not silently regroup the remaining data.
Screenshots stitch reconstructed viewport tiles at the recorded width, including below-fold content that exists in the recorded DOM.
The UI identifies a replacement when the saved representative becomes unavailable.

This is reconstruction, not a historical asset archive.
External images and styles may be missing or may now resolve to changed content.
Masking remains as captured in replay.
Fixed and sticky elements, nested scrolling targets, canvas/video/iframe interactions, unavailable replay windows, oversized pages, and clicks that cannot be aligned are excluded.
Lazy content never recorded cannot be recovered.
There are no SDK changes, public shares, or PNG exports of historical analyses in this version.

Work is bounded by one active analysis per project, 200 candidate recordings, 200 retained page states, 50 variants, and an eight-minute selection budget.
Each recording inspects at most 100 moments and retains at most 20 page states; rendering also limits page height, DOM size, recording size, and output bytes.
The task has a ten-minute soft deadline and a 630-second hard deadline.
Sampling, exclusions, and budget exhaustion produce partial results with coverage counts.
`heatmap_analysis_seconds` and `heatmap_analysis_recordings_total` track processing duration and recording outcomes.

Replay-derived JSON and PNGs are system `ExportedAsset` rows linked to a recording and capped at its expiry.
Existing recording deletion expires those artifacts; the export cleanup task removes stored content.
Read endpoints recheck project, heatmap, recording, deletion, availability, and expiry access before serving results or images, with `Cache-Control: no-store`.
The normal export API and public export tokens cannot expose these artifacts.
An expired or inaccessible recording contributes neither a background nor clicks.
Historical endpoints require a signed-in session; API keys and public replay shares cannot create or retrieve analyses.

Roll out behind the feature flag after applying the web analytics migration and deploying the frontend exporter and exports worker together.
Keep the flag off when the renderer is not configured.
Start with short date ranges and verify background fidelity and the fraction of attributable clicks before widening access.

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
  │   (stats table: any simple or first-pageview breakdown without bounce
  │     rate or session fields, filters and conversion goals included)
  │ needs session fields with filters
  ▼
[5] Full events↔sessions join (unconditional fallback)
```

**Conversion goals on the overview** run ahead of this ladder as two independent reads: the goal-less overview (which climbs the ladder above for visitors) plus a scan of goal events only (`web_overview_conversion_goal_query`). The joined shape grouped every pageview session in range to count the goal, so its memory scaled with traffic; the split scales with conversions. Visitors therefore equal the goal-less visitors card, and a session with a goal event but no pageview or screenview no longer counts as a visitor. Legacy sessions v1 and queries with session or cohort filters keep the joined shape.

**The one-way rule (#72959):** user-facing reads never build precompute buckets inline — `run_inserts` is true only for background-warming requests.
A miss costs one live-path serve; the background warm makes the next identical request a bucket hit.
The dashboard "enqueues precompute" as a side effect; it never waits on it.

## Per-runner dispatch

### WebOverviewQuery (`web_overview.py`)

| #   | Strategy                   | Conditions                                                                                                                            | Tag                                                    |
| --- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| 0   | Conversion-goal split      | Conversion goal + sessions v2/v3 + events-evaluable filters; visitors from the goal-less dispatch below, conversions from goal events | `web_overview_conversion_goal_query` (+ visitors' tag) |
| 1   | Lazy precompute            | Shared gate only — overview has no extra shape restrictions                                                                           | `web_overview_lazy_query`                              |
| 2   | Preaggregated (deprecated) | Modifier on + no conversion goal                                                                                                      | `web_overview_preaggregated_query`                     |
| 3   | Session-id-set             | Filtered + allowlisted + preflight passes (sets `sessionIdPushdown`)                                                                  | `web_overview_session_id_set_query`                    |
| 4   | No-join                    | Unfiltered, no conversion goal                                                                                                        | `web_overview_no_join_query`                           |
| 5   | Full join                  | Fallback (conversion goals with legacy sessions v1, session filters, or cohort filters land here)                                     | `web_overview_query`                                   |

### WebStatsTableQuery (`stats_table.py`) — three lazy families, tried in order

| #   | Strategy                   | Conditions                                                                                                                                                                                                                     | Tag                                                                                                                  |
| --- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| 1   | Paths lazy                 | `breakdownBy` ∈ {Page, InitialPage} + `includeBounceRate`; rejects avg-time-on-page, scroll depth, unsupported orderBy; top-K 10,000 paths/day cap for high-cardinality teams                                                  | `web_stats_paths_lazy_query`                                                                                         |
| 2   | Frustration lazy           | `breakdownBy` = FrustrationMetrics; rejects unsupported orderBy                                                                                                                                                                | `web_stats_frustration_lazy_query`                                                                                   |
| 3   | Simple-breakdown lazy      | ~18 supported breakdowns (DeviceType, Browser, OS, Country, Region, City, Viewport, Timezone, Language, ExitPage, InitialChannelType, InitialReferringDomain/URL, InitialUTM\_\*); rejects bounce rate, avg time, scroll depth | `web_stats_lazy_query`                                                                                               |
| 4   | Preaggregated (deprecated) | Modifier on + no avg-time-on-page + no conversion goal                                                                                                                                                                         | `stats_table_preaggregated*`                                                                                         |
| 5   | Session-id-set             | Page breakdown ± avg time, filtered + allowlisted + preflight                                                                                                                                                                  | `stats_table_session_id_set_path_bounce[_and_avg_time]`                                                              |
| 6   | No-join                    | Unfiltered path-bounce and path-bounce+avg-time; any simple or first-pageview breakdown without bounce rate or session fields (filters and conversion goals ride the single events scan)                                       | `stats_table_no_join_*`                                                                                              |
| 7   | Full join                  | Fallback per shape                                                                                                                                                                                                             | `stats_table_path_bounce`, `stats_table_entry_bounce`, `stats_table_channel_type`, `stats_table_simple_breakdown`, … |

### Traffic metrics alongside conversion goals

`WebStatsTableQuery.includeTrafficMetrics` adds sessions and retains pageviews alongside conversion columns. Traffic visitors and sessions require a pageview or screenview; goal-only sessions contribute to conversions without increasing the traffic denominator. The option defaults to off, preserving existing callers.

Queries with this option bypass the simple-breakdown and paths lazy caches and use the supported live or preaggregated execution path. Event and action conversion goals can carry property filters, which restrict conversions rather than traffic.

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

## Session-grain precompute schema

`web_sessions_dimensional_preaggregated` preserves individual sessions and person identity for attribution reads.
Its sharded storage table lives on the aux cluster; distributed tables on aux and data nodes point to it.
This schema is a prerequisite for the session writer and reader; creating it does not enable either path.

`session_id_v7` uses `UInt128`, matching the raw Sessions v2 and v3 tables and the numeric representation in `events.$session_id_uuid`.
Writers must preserve that representation and only materialize valid UUIDv7 sessions; a null or invalid ID must not become a shared zero-valued ID.
Sessions v1 and arbitrary string IDs require the live query path unless a separate compatible precompute path is available.
The writer, reader, and HogQL schema must use `session_id_v7` consistently before this precompute path is enabled.
The table uses `TTL toDateTime(expires_at)` with whole-part expiry; the lazy computation executor includes the in-flight reader buffer in `expires_at`.

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

| Family          | Precompute                                                                                                 | Live tags                                                                                                                                                                                                                                                                                                                                       |
| --------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Overview        | `web_overview_lazy_query/insert`, `web_overview_preaggregated_query`                                       | `web_overview_conversion_goal_query`, `web_overview_no_join_query`, `web_overview_session_id_set_query` (+`_preflight`), `web_overview_query`                                                                                                                                                                                                   |
| Stats table     | `web_stats_paths_lazy_*`, `web_stats_frustration_lazy_*`, `web_stats_lazy_*`, `stats_table_preaggregated*` | `stats_table_no_join_*` (incl. `stats_table_no_join_first_pageview_attribution`), `stats_table_session_id_set_*` (+`_preflight`), `stats_table_path_bounce[_and_avg_time]`, `stats_table_entry_bounce`, `stats_table_channel_type`, `stats_table_first_pageview_attribution`, `stats_table_frustration_metrics`, `stats_table_simple_breakdown` |
| Goals           | `web_goals_lazy_query/insert`                                                                              | `web_goals_query`                                                                                                                                                                                                                                                                                                                               |
| Vitals          | `web_vitals_paths_lazy_query/insert`                                                                       | `web_vitals_path_breakdown_query`                                                                                                                                                                                                                                                                                                               |
| External clicks | —                                                                                                          | `external_clicks_query`                                                                                                                                                                                                                                                                                                                         |

## Reading a slow tile

Find the request in query_log and check `query_type`.
A `*_lazy_query` taking seconds is a bucket-read problem (rare).
A fast-path or full-join tag on an enrolled team means the lazy gate rejected the query (filters, avg-time-on-page, >90d range, opt-out) or the buckets weren't fresh — in which case a background warm is already in flight and the next identical request should hit.

Conversion goal property filters accept event, person, session and cohort filters. Unsupported filter types fail query validation. `includeTrafficMetrics` also retains session counts for page breakdowns with bounce rate or average time on page, including the join-free strategies.

## Identifying a failed marketing query

Marketing Analytics query errors show a query ID when the request has one.
Use that ID to find the failed request in the query log.
The error's query ID takes precedence over the current request ID; a previous successful response is not a source for the error ID.
Errors outside the query path, such as configuration failures, may have no query ID.

## Marketing metric chart

The standalone metric chart receives prepared series, ISO date labels, a selected breakdown key, and callbacks.
The query-owning caller switches between total and breakdown data and supplies error content, including the failed query ID and retry action.
Chart clicks select the nearest line and return the raw breakdown identity so selections can match table rows even when display labels differ.
An empty string is a selectable breakdown key; `null` clears selection.
Percentage series contain fractions: a value of `0.42` displays as `42.0%` in the axis and tooltip.
The chart keeps existing data visible while refreshing and replaces it with the supplied error if the refresh fails.
Storybook covers loading, refreshing, empty results, errors, and a 520 px scene.
The component does not activate the five-section dashboard or change its queries.
