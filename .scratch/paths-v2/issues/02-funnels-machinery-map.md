# Funnels machinery map

Type: research
Status: claimed
Blocked by: —

## Question

How do funnels compute their numbers end-to-end, and which parts could a paths-style query reuse?

Cover (in `posthog/hogql_queries/insights/funnels/` and related):

- The full pipeline: event query → aggregation → UDF (`aggregate_funnel*`) → response; where each semantic knob lives.
- Ordering modes (ordered/strict/unordered), conversion window (anchoring + units), aggregation targets (person, groups, alternative aggregations), exclusions, sampling, breakdowns.
- The funnel actors/persons query — how drill-down counts stay consistent with the chart.
- Existing funnel↔paths interop: `FunnelPathsFilter` (paths *after/between* funnel steps) in the v1 paths runner and frontend; the v1 "view funnel" affordance.
- UDF payload shapes and constraints (`posthog/user_scripts/` or wherever `aggregate_funnel` lives) — could it emit per-step sequences a paths query needs?
- Concrete reusable units (class/function names + file:line): event filtering, entity→expr, window handling, actor resolution.
- Facts bearing on "a path segment A→B equals which funnel?": what a strict-order 2-step funnel counts vs what the draft v2 runner counts (per-session transitions, gap-based session split, consecutive-dedupe).

Facts only — the semantics decision belongs to [Counting semantics](03-counting-semantics.md).

## Answer

Findings: [research/funnels-machinery.md](../research/funnels-machinery.md)
