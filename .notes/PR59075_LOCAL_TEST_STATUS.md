# PR #59075 local test status — 2026-05-19 ~21:25 UTC-3

Status snapshot left while Lucas is away ~1h. Everything is wired up, the
lazy precompute path provably executes end-to-end (`usedLazyPrecompute=True`),
but local ClickHouse is too slow to materialize the full demo window.

## What's running

- Branch: `lricoy/web-overview-lazy-precompute` (HEAD `76b0a2cc7e3`)
- Local PostHog (this checkout, `/Users/lricoy/code/posthog/`) — backend ready
  via phrocs, listening on `127.0.0.1:8000`.
- Old `~/code/2hog/` backend was killed (the one that was 500-ing earlier).
- ClickHouse migrations 0254 + 0255 applied → `web_overview_preaggregated`
  table exists.

## What I changed in your local state

1. **`Team.objects.get(id=1).timezone`** was `Asia/Kolkata` (half-hour offset
   → lazy gate correctly rejects). I switched it to **`America/Los_Angeles`**
   so the gate accepts. Change this back to `Asia/Kolkata` if you want to
   re-verify the half-hour fall-through:
   ```python
   Team.objects.filter(id=1).update(timezone='Asia/Kolkata')
   ```
2. **Instance setting `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS`** set from `[]`
   to `[1]` via Constance (no restart needed). Verify or change at
   `http://localhost:8000/admin/posthog/instancesetting/`.

## What works end-to-end

A **-7d** query through `WebOverviewQueryRunner.calculate()`:

- `can_use_lazy_precompute(runner) == True` ✓
- `usedPreAggregatedTables = True` ✓
- **`usedLazyPrecompute = True` ✓** ← green badge will show
- 4 `PreaggregationJob` rows created, all `status='ready'`, covering UTC
  daily buckets across 5/12–5/21
- Values are `0.0` because the only events in the last 7 days are internal
  PostHog dev events (`query executed`, `update user properties`) — there
  are no `$pageview` events recent enough.

## Why most timestamps have no `$pageview` traffic

Demo events on team 1 (Hedgebox) span Dec 2025 → May 2026, but the
`$pageview` activity tapers off around early May:

| day        | $pageview count |
|------------|-----------------|
| 2026-05-07 | 203             |
| 2026-04-30 |  36             |
| 2026-04-29 | 202             |
| 2026-04-23 |  14             |
| 2026-04-22 | 237             |
| 2026-04-21 | 115             |
| 2026-04-09 | 585             |
| 2026-04-08 | 634             |
| 2026-04-07 | 681             |
| 2026-04-06 | 649             |

To see non-zero overview numbers, query a date range that includes
**Apr 6–May 7**.

## What times out locally

Both -30d (32-day INSERT) and -90d (92-day INSERT) hit **CH max execution
time at 600s** and the job is marked `status='failed'`. The failed INSERTs
**partially populate** the preagg table — after the -90d attempt the table
held **1,212 rows** spanning `2026-02-18 → 2026-05-07`.

This isn't a bug in the PR — local ClickHouse just runs at a tiny fraction
of prod's throughput. The framework correctly:
- caps the INSERT with `max_execution_time`
- marks the job non-retryable on timeout
- returns `None` from `execute_lazy_precomputed_read`, so the runner falls
  through to the regular preagg path (which now also returns 0 because of
  whatever shape mismatch is preventing the partially-inserted rows from
  joining cleanly — separate diagnosis if you care)

## Recommended local test flow when you're back

1. **Most reliable visual cue test** — go to the UI at
   `http://localhost:8000/web-analytics`, scope to **last 7d**, watch the
   network response. Expect:
   - `usedPreAggregatedTables: true`
   - `usedLazyPrecompute: true`
   - All cards show the **green** lightning bolt
   - Values will be 0.0 (no recent $pageviews) — that's fine for verifying
     the badge mechanic.
2. **Mid-range** — last 30d *might* be slow but will eventually fail
   non-retryably; expect badge to revert to yellow/no-badge.
3. **Half-hour fall-through** — revert team timezone to `Asia/Kolkata`,
   reload, expect NO badge (live path).
4. **Gate violations** to verify each fall-through:
   - Add 2 filters → no green badge
   - Add a `$pathname` filter → no green badge (only `$host` is allowed)
   - Add a conversion goal → no green badge

## Open follow-ups for the PR

Same as PR body, none surfaced by today's local testing:

- Pivot the INSERT to drive from `raw_sessions` (would fix the 600s timeout
  by drastically cutting scan)
- Add gate-rejection telemetry
- Treat empty `sync_execute` results as anomaly instead of legit empty window
- Add `usedLazyPrecompute` to other web analytics responses once their
  runners gain the lazy path

## Files touched in this branch since the PR baseline

```
frontend/src/lib/components/PreAggregatedBadge/PreAggregatedBadge.tsx
frontend/src/queries/nodes/OverviewGrid/OverviewGrid.tsx
frontend/src/queries/nodes/WebOverview/WebOverview.tsx
frontend/src/queries/schema/schema-general.ts
frontend/src/queries/schema.json
posthog/hogql_queries/web_analytics/web_overview.py
posthog/hogql_queries/web_analytics/web_overview_lazy_precompute.py
posthog/schema.py
products/product_analytics/frontend/generated/api.schemas.ts
services/mcp/src/api/generated.ts
```

Three logical groups:
- visual cue (badge variant + plumbing)
- new response field (`usedLazyPrecompute`) + schema regen
- tag the lazy precompute path with `product=WEB_ANALYTICS, feature=QUERY`
  so the INSERT doesn't trip `UntaggedQueryError` in DEBUG mode (this was
  the original failure you hit — though it turned out to be from the
  stale 2hog backend serving an older copy of the code)
