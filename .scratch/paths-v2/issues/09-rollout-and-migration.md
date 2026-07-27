# Rollout and migration

Type: grilling
Status: open
Blocked by: 07

## Question

How do users (and their saved insights) get from v1 paths to v2?

Decide:

- **Flag lifecycle**: `PRODUCT_ANALYTICS_PATHS_V2` today only swaps the viz component on v1 data (`InsightVizDisplay.tsx:383`) — does the same flag gate the new query, or a fresh flag? Beta cohort, opt-in banner, or silent rollout?
- **Saved insights**: v1 `PathsQuery` insights keep working indefinitely? The draft planned a "convert to v2" button with warnings for non-convertible settings — which v1 settings have no v2 equivalent, and what happens to them?
- **New-insight default**: when does the paths tab create a v2 query by default; do v1 and v2 coexist in the insight-type list ([PR #29364](https://github.com/PostHog/posthog/pull/29364) added a separate saved-insights filter entry)?
- **Surfaces**: dashboards, notebooks, subscriptions/exports, Max — confirm each renders v2 or falls back cleanly.
- **`edgeLimit` retirement**: the 50-edge limit dies with v1 — no v2 equivalent to map it to; confirm.
