# Paths v2 — wayfinder map

Label: wayfinder:map
Tracker: local markdown (`.scratch/paths-v2/`), per the wayfinder local-tracker convention.
Tickets live in [issues/](issues/); a ticket is unblocked when every ticket in its `Blocked by:` line is `resolved`.

## Destination

An implementation-ready spec for paths v2:
counting semantics under which any displayed path segment A→B can be recreated as a funnel with identical results,
a row-by-column limited visualization (max steps × max rows per step, replacing the flat 50-edge limit),
and a decided build + rollout route that reuses what [PR #29364](https://github.com/PostHog/posthog/pull/29364) already proved.
Done when a build session can start without further product decisions.

## Notes

- Tracking issue: [Paths V2 #37285](https://github.com/PostHog/posthog/issues/37285).
- Prior work: merged viz [PR #28495](https://github.com/PostHog/posthog/pull/28495) (in-repo `frontend/src/scenes/paths-v2/`, behind flag `PRODUCT_ANALYTICS_PATHS_V2` = `paths-v2`, still consumes v1 `PathsQuery` results); draft query [PR #29364](https://github.com/PostHog/posthog/pull/29364) (closed unmerged, branch `paths-v2-separation` = `8cbbcfdc`, adds `PathsV2Query` + 450-line runner + row/column limit UI).
- Key code: v1 runner `products/product_analytics/backend/hogql_queries/paths/paths_query_runner.py`; funnels `posthog/hogql_queries/insights/funnels/`; viz switch `frontend/src/queries/nodes/InsightViz/InsightVizDisplay.tsx:383`.
- Standing constraints from Thomas: maximize reuse of funnels code; a path segment must convert to a funnel with identical numbers; row-by-column limit replaces `edgeLimit` (default 50).
- Skills: `/grilling` + `/domain-modeling` on grilling tickets; `/prototype` on the visualization ticket; `/research` for research tickets. Any code follows repo `CLAUDE.md`.
- Deviation from the wayfinder default: research findings live in [research/](research/) on this map's PR branch, not on `research/*` branches (cloud runs can only push `posthog-code/*` branches).
- This is a planning map: tickets resolve decisions; the build itself starts after the map is done.

## Decisions so far

<!-- one line per closed ticket: gist + link -->

- [Draft-work autopsy](issues/01-draft-work-autopsy.md) — PR #29364 is a complete, mostly-tested vertical slice of a separate `PathsV2Query` (5 steps × 3 rows defaults, gap-based sessions, "other" bucketing) whose tip doesn't compile; master since evolved the very scene files it rewrites, moved the v1 runner to `products/product_analytics/`, and changed codegen — generated schema must be regenerated, not rebased.
- [Funnels machinery map](issues/02-funnels-machinery-map.md) — all funnels run through one Rust UDF (`aggregate_funnel_v12`) counting unique actors per step in a step-1-anchored window; drill-downs and v1 `FunnelPathsFilter` wrap the same UDF subquery (consistency by construction); today's "view funnel" from paths is lossy; path-edge==funnel equality needs per-actor semantics or a new UDF mode; reusable: `FunnelEventQuery`, step exprs, window helpers, actors stack, `journeys_for`.

## Not yet specified

- **Aggregation by sessions/groups** ("event journeys", [#33488](https://github.com/PostHog/posthog/issues/33488)) — direction named in the tracking issue; spec waits on [Counting semantics](issues/03-counting-semantics.md).
- **Path item derivation** — which events produce which path items: pageview URL + path cleaning, screen names, custom events, property-based expansion ([#11086](https://github.com/PostHog/posthog/issues/11086)), arbitrary/`$`-event selection ([#17161](https://github.com/PostHog/posthog/issues/17161)), wildcards/aliases. Sharpens after [MVP scope cut](issues/06-mvp-scope-cut.md).
- **Performance guardrails** — hard limits on steps/rows, sampling, query cost on large teams. Depends on the engine chosen in [Funnel-reuse strategy](issues/04-funnel-reuse-strategy.md).
- **Insight-platform integration** — `PathsV2Summary`/details panel, exports, endpoints/HogQL exposure, Max context formatting (`ee/hogai/context/insight/format/paths.py`). Sharpens after [Build route](issues/07-build-route.md).
- **v1 sunset** — criteria and timeline for removing v1 paths. Sharpens after [Rollout and migration](issues/09-rollout-and-migration.md).

## Out of scope

- Further v1 paths/sankey improvements beyond keeping it working — v2 replaces it.
- Path cleaning rule _management_ (web analytics settings surface) — v2 only consumes the rules.
- MCP tool-call paths ([#69586](https://github.com/PostHog/posthog/issues/69586)) — different surface; may consume paths v2 later, not part of this destination.
