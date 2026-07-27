# Funnels machinery map

Type: research
Status: resolved
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

Findings: [research/funnels-machinery.md](../research/funnels-machinery.md). Resolved 2026-07-27 by a `/research` agent. Gist:

- **One pipeline, one UDF.** Every funnel mode runs through the Rust `aggregate_funnel` ClickHouse executable UDF (`funnel-udf/src/`, deployed `aggregate_funnel_v12`); no non-UDF path remains. SQL side: `FunnelEventQuery` flags events with matched step indices → `groupArray` per `aggregation_target` → `arrayJoin(aggregate_funnel(...))` (`posthog/hogql_queries/insights/funnels/funnel.py:115-206`).
- **One best-attempt row per actor.** The UDF returns `(step_reached, breakdown, inter-step timings, matched event UUIDs [cap 10/step], steps bitfield)` and stops after the first full conversion (`funnel-udf/src/steps.rs:190-229`). Step counts = `countIf(bitAnd(steps_bitfield, 1<<i))` — unique actors, period.
- **Four equality blockers vs the draft's per-session counting:** (1) funnels count 1/actor, draft counts 1/qualifying session; (2) funnel window is fixed-length anchored at the step-1 event (default 14d), paths sessions are inactivity-gap based; (3) strict-order adjacency is over *all* team events — strict funnels deliberately skip entity prefilters (`funnel.py:116-119`) — while a path edge means "next displayed path item" after filtering/cleaning/dedupe; (4) funnels need both A and B inside the date range (`funnel_event_query.py:631-645`). So "path edge == funnel" is unreachable with any *current* funnel config unless paths adopt per-actor semantics or the UDF grows a mode.
- **Consistency-by-construction exists and v1 paths already uses it:** `FunnelUDF.actor_query` wraps the same UDF subquery with `bitTest(steps_bitfield, step-1)` (`funnel.py:432-454`); v1 `FunnelPathsFilter` reuses that actors stack, joining events to `funnel_actors` time-bounded by UDF-derived step timestamps (`paths_query_runner.py:151-278`). Proven pattern for funnel↔paths numeric consistency.
- **Today's "view funnel" from a path is lossy:** builds a default *ordered* 14-day funnel from the node's ancestor chain, carries only `date_from`, sets no order type/window (`frontend/src/scenes/paths/pathsDataLogic.ts:38-63, 239-262`) — never matched path counts.
- **A per-session/all-attempts UDF mode is feasible but a deploy project:** `funnel_order_type` is a free string arg and per-step UUIDs/timings already flow out, but a new mode needs the versioned binary build + ClickHouse rollout + `UDF_VERSION` flip (`funnel-udf/README.md:11-22`, `posthog/udf_versioner.py:12`). Constraints: ≤32 steps (`UInt32` bitfield), per-actor arrays in CH memory.
- **Cleanest reuse targets:** `FunnelEventQuery` (date range, sampling, entity prefilter, aggregation target incl. groups/HogQL), `_build_step_query` (entity→expr), `funnel_window_interval_unit_to_sql` + `conversion_window_limit`, `FunnelQueryContext` defaults, the `InsightActorsQueryRunner`/`ActorsQueryRunner` stack, test helpers `journeys_for` + order-type-parameterized factories (`funnels/test/breakdown_cases.py`).
- **Import direction:** funnels are core, paths product-owned; `tach.toml` allows both directions today but the cycle already forces an inline import (`paths_query_runner.py:235`). Shared primitives belong in core to survive future product isolation.
