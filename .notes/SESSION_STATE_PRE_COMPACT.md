# Session state — pre /compact, 2026-05-19 ~19:43 UTC

## Where we are right now

**Branch checked out for testing:** `lricoy/web-overview-lazy-precompute`
**PR:** https://github.com/PostHog/posthog/pull/59075 (draft)
**Goal:** Lucas wants to play around locally + I help him test.

User invoked `/compact` after this snapshot.

## What the PR does (PR #59075)

`feat(web-analytics): lazy precompute path for web_overview_query`

- `web_overview_query` is the **highest-volume + highest-cost** web analytics query
  (14.7k runs/24h on prod-us, 10.5k seconds/24h ClickHouse cost, ~78 slow incidents/day).
- This PR wires it through the existing `lazy_computation` framework
  (`products/analytics_platform/backend/lazy_computation/`) — precomputed UTC
  hourly buckets, computed on first read, cached for subsequent reads.
- MVP eligibility gate: only fires for queries with **at most 1 filter and only
  on `$host`**. Conversion goals, sampling, sessions-v2 UUID mode, non-string
  `$host` values, date ranges > 180 days, half-hour-offset timezones — all
  fall through to the live path.

4 commits on the branch:

1. `6a448083876` — feat: lazy precompute path for web_overview_query (initial)
2. `9d7f562f89f` — fix: timezone correctness + QA hardening
3. `d66903b3fdf` — fix: drop broken `select_sequential_consistency`, tighten session pad, add docs
4. `76b0a2cc7e3` — fix: widen lazy precompute session pad back to 24h (HEAD)

Full design rationale in `products/web_analytics/PRECOMPUTATION.md` on the branch.

## Key files to read when testing

- `posthog/hogql_queries/web_analytics/web_overview_lazy_precompute.py` (NEW, ~300 lines) — the strategy
- `posthog/hogql_queries/web_analytics/web_overview.py` — short-circuit wiring (look for `_calculate` change)
- `posthog/hogql_queries/web_analytics/test/test_web_overview_lazy_precompute.py` — parametrized tests
- `products/web_analytics/PRECOMPUTATION.md` — design + known limitations
- `posthog/clickhouse/migrations/0254_web_overview_preaggregated.py` + `0255_web_overview_preaggregated_repartition.py` — table creation
- `posthog/settings/dynamic_settings.py` — `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` flag (defaults empty = fail-closed)

## How to test locally

Per the PR body, the testing flow is:

1. **Apply ClickHouse migrations**: 0254 + 0255 must run to create `web_overview_preaggregated` table.
2. **Enable team for lazy path**: set the env var or dynamic setting
   `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` to include a team_id (e.g. `1` or `2`).
3. **Send a WebOverviewQuery** for that team — should short-circuit via the lazy path on
   first call (creates the precompute job + waits), serve from cache on subsequent calls.
4. **Verify** by checking the response's `usedPreAggregatedTables=True` flag and that
   `READY` precompute jobs were created for the time window.

Per the PR body, Lucas already ran it locally and confirmed `usedPreAggregatedTables=True`
+ READY jobs created for UTC / LA / Tokyo teams; Kolkata team (half-hour offset) correctly
falls through with 0 jobs.

## Eligibility gate logic (don't trip it during testing)

These conditions cause fall-through to live (not bugs, expected):

- Team timezone has non-integer hour offset (Kolkata, Newfoundland, Nepal, Iran)
- Query has conversion goals
- Query has sampling
- Sessions-v2 in UUID mode
- More than 1 user filter
- A filter on anything other than `$host`
- Non-string `$host` value
- Date range > 180 days

## Open follow-ups per the PR body (not blocking but worth noting)

- Pivot the INSERT to drive from `raw_sessions` (filtered by `session_id_v7` timestamp)
- Add gate-rejection telemetry
- Treat empty `sync_execute` results as anomaly instead of legit empty window
- Add a separate `usedLazyPrecompute` response field (requires schema regen)
- Re-type `uniq_sessions_state` to `(uniq, UUID)` for UUID session mode

## Other open work this session

- **PR #59078** (`lricoy/web-analytics-simple-breakdown-tag-split`): rename
  MainQueryStrategy → SimpleBreakdownStrategy + carve out ChannelTypeStrategy.
  Status: 2 approvals (auto + arthurdedeus), 63 CI checks green, 85 in progress
  on `8d4fc08940c`. Awaiting stamphog. Ready-for-review (not draft).
- **Local `.notes/web-analytics-check-2026-05-19/`**: 22 iterations of
  monitoring data + cross-iteration trendline. Per-strategy tag rollout
  fully converged at 04:09:51 UTC today.
- **Team 2 timeout dossier**: 23 TIMEOUT_EXCEEDED in 48h on team 2 (PostHog's
  own analytics dashboard) — 7 on path_bounce, 7 on frustration_metrics, 6 on
  main_query, 2 on entry_bounce, 1 on external_clicks. All 60-second wall-hits.
  This PR (overview lazy precomp) doesn't directly help these, but the *other*
  lazy-precomp PR (path-bounce on a different branch) targets the 7 path_bounce
  ones. Frustration_metrics and main_query timeouts are NOT covered by either
  lazy-precomp branch yet.
- **`posthog-code/feat-web-vitals-signals-preserved`** branch on remote: safety
  copy of an unrelated signals commit. Can be deleted once Lucas confirms the
  canonical signals branch has it.

## Right after /compact, suggested first action

Read this file. Then ask Lucas what specifically he wants to test (the overview
lazy path end-to-end, a particular eligibility gate edge case, the PR's open
follow-ups, etc).
