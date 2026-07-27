# Funnels machinery end-to-end, and what a paths-style query can reuse

**TL;DR.**
All funnel viz modes on master run through a single ClickHouse executable UDF (`aggregate_funnel`, a Rust binary in `funnel-udf/`, deployed versioned as `aggregate_funnel_v12`): a HogQL inner query flags each event with the step indices it matches, `groupArray`s each actor's events into one sorted array, and `arrayJoin`s the UDF, which runs the ordered/strict/unordered state machine per actor and returns exactly one best-attempt row per actor (`step_reached`, breakdown, inter-step timings, matched event UUIDs per step, a steps bitfield).
Step counts are unique-actor counts derived from that bitfield; the actors drill-down and funnel-to-paths interop wrap the *same* UDF subquery with a WHERE clause, which is why drill-downs match chart numbers by construction.
The decisive gap vs the draft paths-v2 per-session transition counting: the UDF collapses each actor to one attempt (a person converting in three sessions counts once), its window is anchored at the step-1 event (not an inactivity gap), and strict-order adjacency is over *all* of the actor's events, not just displayed path items — so "path edge A→B == some funnel" is not achievable with any current funnel configuration without either a new UDF mode or accepting per-actor semantics.
Everything below cites master.

## 1. End-to-end pipeline for a plain steps funnel

**Runner and class selection.**
`FunnelsQueryRunner` (`posthog/hogql_queries/insights/funnels/funnels_query_runner.py:76`) builds a `FunnelQueryContext` (`funnels_query_runner.py:94-101`) and picks the funnel class by viz type: `FunnelUDF` for steps, `FunnelTrendsUDF` for trends, `FunnelTimeToConvertUDF` for time-to-convert (`funnels_query_runner.py:643-651`).
There is **no non-UDF SQL path left** for computing funnels — `posthog/hogql_queries/insights/funnels/__init__.py:3-6` exports only UDF classes; the legacy window-function machinery survives only as vestigial helpers on `FunnelBase` (`base.py:517-544` `_get_sorting_condition`, `base.py:558-622` `_get_step_counts_query`) that no live query path reaches (`FunnelsFilter.useUdf` is dead in the backend — only the generated schema field remains, `posthog/schema.py:23314`).
`to_query()` returns `funnel_class.get_query()` (`funnels_query_runner.py:129-130`), executed via `execute_hogql_query` with `max_bytes_before_external_group_by` set so funnels never OOM (`funnels_query_runner.py:289-301`).

**Event filtering — `FunnelEventQuery`.**
`FunnelBase._get_inner_event_query` (`base.py:260-283`) delegates to `FunnelEventQuery` (`posthog/hogql_queries/insights/funnels/funnel_event_query.py:69`).
Its `to_query()` (`funnel_event_query.py:108-185`) groups steps by source table (events vs data-warehouse tables, UNION ALL when mixed with `aggregation_target` coerced to string, `funnel_event_query.py:163-185`).
The events-table branch (`funnel_event_query.py:187-225`) selects `timestamp`, `aggregation_target`, extra fields (`uuid`, `$session_id`, `$window_id`), and WHEREs on:
date range (`funnel_event_query.py:631-645`), entity prefilter `event IN (...)` over all step and exclusion events (`funnel_event_query.py:655-699`, disabled for "All events"),
query-level property filters + test-account filters via `Properties` (`funnel_event_query.py:701-702`; `posthog/hogql_queries/insights/utils/properties.py:59`),
a non-empty aggregation-target guard for non-person aggregation (`funnel_event_query.py:603-609`),
and an OR of the step conditions unless `skip_step_filter` (`funnel_event_query.py:216-218`, `428-436`).

**Entities become step flags.**
For each series entity, a column `step_{i}` is emitted as `if(<condition>, 1, 0)` (`funnel_event_query.py:319-330`); the condition is built by `_build_step_query` (`funnel_event_query.py:349-410`): `event = '<name>'` for `EventsNode`, `action_to_expr(action)` for `ActionsNode`, OR-composition for `GroupNode`, constant 1 for all-events, plus `property_to_expr` per-entity property filters and first-time-for-user subqueries (`funnel_event_query.py:394-407`).
Exclusions become `exclusion_{i}` flags the same way (`funnel_event_query.py:332-347`), exploded per step index by `exclusions_by_index` (`funnel_event_query.py:96-106`).

**Per-actor data reaches the UDF.**
`FunnelUDF._inner_aggregation_query` (`posthog/hogql_queries/insights/funnels/funnel.py:115-206`) — "the function that calls the UDF … used by both the query itself and the actors query" (`funnel.py:113-114`) — does, per `aggregation_target` (GROUP BY at `funnel.py:201`):
`arraySort(t -> t.1, groupArray(tuple(toFloat(timestamp), uuid, <prop>, arrayFilter(x -> x != 0, [1*step_0, 2*step_1, …, -1*exclusion_…]))))` (`funnel.py:125,128-130,176-181`) — i.e. each event carries the 1-indexed steps it matches, exclusions as negative indices;
a pre-filter `event_array_filter()` drops events that match ≤1 step and are sandwiched between identical neighbors, to shrink UDF payloads (`funnel.py:91-111`);
then `arrayJoin(aggregate_funnel(max_steps, conversion_window_seconds, breakdown_attribution, funnel_order_type, prop_vals, optional_steps, events_array))` (`funnel.py:183-191`).
Strict-order funnels feed **all** events (skip step and entity filters, `funnel.py:116-119`) because any event can break strictness.
Function name selection: `aggregate_funnel` / `aggregate_funnel_array` (array breakdowns) / `aggregate_funnel_cohort` (`funnel.py:132-137`); names are suffixed with the deployed version (`_v12`) on cloud/CI via `augment_function_name` (`posthog/hogql/functions/udfs.py:36-41`, `posthog/udf_versioner.py:12`).

**What the UDF is and what it returns.**
It is a Rust binary (`funnel-udf/src/`), registered in ClickHouse as an `executable_pool` UDF (`posthog/user_scripts/v12/user_defined_function.xml`, `aggregate_funnel_v12` block):
args `(num_steps UInt8, conversion_window_limit UInt64, breakdown_attribution_type String, funnel_order_type String, prop_vals Array(Nullable(String)), optional_steps Array(Int8), value Array(Tuple(Nullable(Float64) timestamp, UUID, Nullable(String) breakdown, Array(Int8) steps)))`;
return `Array(Tuple(Int8, Nullable(String), Array(Float64), Array(Array(UUID)), UInt32))` = per prop_val: `(step_reached [0-indexed furthest step, -1 if none/excluded], breakdown value, timings [pairwise seconds between consecutive matched steps of the best attempt, steps.rs:222-226], matched event UUIDs per step [capped at MAX_REPLAY_EVENTS=10, funnel-udf/src/steps.rs:60], steps bitfield [bit i set = step i+1 reached, steps.rs:309])`.
The SQL aliases these as `step_reached`, `steps` (= step_reached + 1, backward compat), `breakdown`, `timings`, `steps_bitfield` (`funnel.py:192-197`), and `HAVING step_reached >= 0` drops non-entrants and excluded actors (`funnel.py:202`).

**Unique-actor counts per step.**
First grouping by `breakdown`: `countIf(bitAnd(steps_bitfield, 1 << i) != 0) AS step_{i+1}` (`funnel.py:220-222`) — each actor contributes at most 1 per step, from their single best attempt — plus `groupArrayIf(timings[i], …)` conversion-time arrays (`funnel.py:225-230`).
Second grouping applies the breakdown limit / "Other" bucket and sums (`funnel.py:240-244, 309-328`), computes avg/median conversion times and a breakdown-agnostic `total_median_conversion_time` (`funnel.py:284-305`).
`_format_single_funnel` walks steps in reverse and serializes counts (`funnel.py:467-516`), applying `correct_result_for_sampling` (`base.py:191,228`; `posthog/queries/util.py:127-139`).
Person identity comes from the HogQL events table's `person_id` (override-aware); the funnel layer just selects it (`funnel_event_query.py:583-587`).

## 2. Semantic knobs

**Ordering modes** (`StepOrderValue`, `frontend/src/types.ts:1844-1848`; default `ordered`, `frontend/src/queries/schema/schema-general.ts:1795-1796`):

- `ordered` ("sequential"): classic DP over the sorted event array (`funnel-udf/src/steps.rs:104-338`). Any events may occur between steps. Each step-k event extends the attempt whose step k-1 entry is within the window (`steps.rs:250-273`); a new step-1 event re-anchors slot 1 (`steps.rs:140-146, 312-317`); the per-actor result is the max step ever reached (`steps.rs:196-229`), with early exit once the full funnel completes (`steps.rs:190-194`). Same-timestamp event groups are handled by permuting single-step copies, ignoring strictness/exclusions for that group (`steps.rs:165-188`).
- `strict`: same DP, but after each event every step slot whose step list does not include that event is reset (`steps.rs:331-337`); combined with the all-events feed (`funnel.py:116-119`) this means *any* intervening event of any kind (matching neither step) breaks the sequence — B must be the literally next event after A.
- `unordered`: separate implementation (`funnel-udf/src/unordered_steps.rs:33-170`): a sliding window of per-step deques; `num_steps_completed` counts distinct steps with at least one event inside the conversion window (`unordered_steps.rs:91-130`); any exclusion event clears all state (`unordered_steps.rs:132-139`). Steps are displayed as "Completed N steps" (`base.py:184-193`); only step-1 breakdown attribution allowed (`funnel.py:213-218`); exclusions must span the whole funnel (`funnel_validation_rules.py:73-79`).

**Conversion window.**
`funnelWindowInterval` default 14, `funnelWindowIntervalUnit` default `day` (`funnel_query_context.py:113-119`; schema defaults `schema-general.ts:1799-1802`; units second…month, `frontend/src/types.ts:3501-3508`), converted to seconds via `DATERANGE_MAP` (`funnel.py:75-78`).
Anchored at the **step-1 event of the current attempt**: the entry timestamp is propagated unchanged through every later step (`steps.rs:304-310`), and each step-k event must satisfy `event.timestamp - entry_timestamp <= window` (`steps.rs:254-256`) — so the *whole funnel* must complete within one window of the entry event, not step-to-step.
(The legacy SQL encoded the same thing: `latest_i <= latest_0 + INTERVAL n unit`, `base.py:530-534`.)

**Aggregation target.**
Default `person_id`; `aggregation_group_type_index` switches to `$group_{n}`; `funnelsFilter.funnelAggregateByHogQL` parses an arbitrary HogQL expression (`funnel_event_query.py:583-601`), though the typed enum exposes only `properties.$session_id` (`posthog/schema_enums.py:205-207`).
Session aggregation additionally carries `any(person_id)` through the UDF query so the persons modal can resolve people (`funnel.py:70-73, 167-171, 442-443`).
Non-person targets get a non-empty filter (`funnel_event_query.py:603-609`).

**Exclusions.**
Schema: `FunnelExclusionEventsNode/ActionsNode` with `funnelFromStep`/`funnelToStep` (`schema-general.ts:1768-1777`).
An exclusion attaches to every step index in `(from, to]` (`funnel_event_query.py:96-106`), reaches the UDF as negative step indices (`funnel.py:128-130`), and if it lands within the window between the bracketing steps it marks the attempt excluded (`steps.rs:241-248, 276-287`); an actor whose best attempt is excluded returns `step_reached = -1` and is dropped from **all** steps (`steps.rs:200-203`; `funnel.py:202`).
Validation forbids overlap with step entities and bad ranges (`funnel_validation_rules.py:57-105`).

**Date range anchoring.**
Every counted event — entry *and* completion — must lie within `[date_from, date_to]` inclusive (`funnel_event_query.py:631-645`); conversions completing after `date_to` are simply not counted, and there is no "entry in range, completion anywhere" behavior for the steps viz.
Default range is the last 7 days (`posthog/hogql_queries/utils/query_date_range.py:164-167`; `posthog/utils.py:96`); `dateRange.explicitDate` skips date truncation (`funnels_query_runner.py:657-669`).
`daysOfWeek` filtering applies to the TRENDS viz only (`funnel_event_query.py:647-653`).
Trends can optionally hide periods whose window hasn't elapsed (`funnel_trends.py:509-532`; `schema-general.ts:1831-1836`).

**Sampling.**
`query.samplingFactor` becomes a ClickHouse `SAMPLE` clause on the events table (`funnel_event_query.py:611-617`); counts are scaled back up in serialization (`base.py:191,228`; `posthog/queries/util.py:127-139`).

**Breakdowns and attribution.**
Per-event `prop_basic` is computed for person/event/cohort/group/session/hogql/data-warehouse breakdown types (`funnel_event_query.py:438-539`); cohort breakdowns join a cohort-people union (`base.py:285-318`).
Attribution (`breakdownAttributionType`, default `first_touch`, `funnel_query_context.py:105-107`): per-actor `prop_vals` are computed as `argMinIf`/`argMaxIf`/`groupUniqArray` over the actor's events (`funnel.py:28-54`); the UDF then runs the whole state machine once per prop_val (`steps.rs:111-113`), with `all_events` filtering events to the matching breakdown (`steps.rs:129-135`) and `step_{n}` attribution rejecting entries whose breakdown mismatches at the attribution step (`steps.rs:106-109, 288-293`).
Breakdown result limit + "Other" bucketing at `funnel.py:232-244, 324`.

**Optional steps** (`optionalInFunnel`, `schema-general.ts:865`): passed as 1-indexed list (`funnel.py:152-157`); the UDF backtracks past unsatisfied optional steps when matching (`steps.rs:250-267`) and subtracts skipped optionals from the reported step index (`steps.rs:206-221`); validation restricts them to ordered/strict steps funnels (`funnel_validation_rules.py:108-150`).

**`funnelStepReference`** (total vs previous) is display-only math in the frontend (`schema-general.ts:1804-1805`; `frontend/src/scenes/funnels/funnelDataLogic.ts:841`); the backend always returns absolute unique counts per step.

**Compare to previous period** runs two full funnel queries in parallel threads and merges tagged rows (`funnels_query_runner.py:374-447`, `_run_in_parallel` at `323-372`).

## 3. The funnel actors (drill-down) query

Flow: `FunnelsActorsQuery` (`schema-general.ts:4904-4920`; `funnelStep` 1-indexed, negative = dropped off at |step|) → `InsightActorsQueryRunner`, which sets `funnels_runner.context.actorsQuery` and calls `to_actors_query()` (`posthog/hogql_queries/insights/insight_actors_query_runner.py:86-89`) → `FunnelsQueryRunner.to_actors_query` (`funnels_query_runner.py:132-140`, with compare='previous' re-pinning the context to the shifted date range) → `FunnelUDF.actor_query` (`funnel.py:432-454`).

**Same numbers by construction**: `actor_query` selects `aggregation_target AS actor_id` **from the very same `_inner_aggregation_query()`** (same UDF invocation, same filters; `funnel.py:444`) and applies `_get_funnel_person_step_condition` (`funnel.py:332-380`):
converted at step N → `bitTest(steps_bitfield, N-1)` (`funnel.py:349`) — the same bitfield the chart counted with `countIf(bitAnd(...))`;
dropped off at step N → reached the last *required* prior step but not step N (`funnel.py:351-367`);
optional breakdown-value pinning via `arrayFlatten(array(breakdown)) = …` (`funnel.py:369-377`).
Matched step events/timestamps for recordings come off the UDF's UUID arrays re-joined to the actor's own events map (`funnel.py:80-88, 382-396, 398-430`).
Trends actors filter the trends UDF output on `entrance_period_start` and `success_bool` instead (`funnel_trends.py:307-370`).
Funnel correlation reuses the identical `FunnelUDF.actor_query` (`posthog/hogql_queries/insights/funnels/funnel_correlation_query_runner.py:142, 761`).
`ActorsQueryRunner` (`posthog/hogql_queries/actors_query_runner.py:38`) then wraps the actor query to hydrate person/group profiles — it never re-derives membership.

## 4. FunnelPathsFilter interop today

Schema: `FunnelPathsFilter = { funnelPathType, funnelSource: FunnelsQuery, funnelStep? }` on `PathsQuery` (`schema-general.ts:2003-2015`); `FunnelPathType` = before/between/after step (`frontend/src/types.ts:3030-3034`).

**Backend** (`products/product_analytics/backend/hogql_queries/paths/paths_query_runner.py`):
`funnel_join()` (`paths_query_runner.py:231-278`) constructs a `FunnelsActorsQuery(source=funnelSource, funnelStep=funnelStep)` and runs it through `InsightActorsQueryRunner`, toggling `includeTimestamp` (after/before) or `includePrecedingTimestamp` (between) on the funnel context (`paths_query_runner.py:254-260`), then INNER JOINs `events` to `funnel_actors` on the funnel's aggregation target — mirroring `FunnelEventQuery._aggregation_target_expr` for group/HogQL aggregation (`paths_query_runner.py:203-229`).
`handle_funnel()` (`paths_query_runner.py:151-201`) then time-bounds the path scan per actor:
AFTER step → `events.timestamp >= funnel_actors.timestamp` (the actor's step-N timestamp), extended by one conversion window when `funnelStep < 0` (drop-off) (`paths_query_runner.py:169-178`);
BEFORE step → `events.timestamp <= funnel_actors.timestamp`;
BETWEEN steps → `min_timestamp <= events.timestamp <= max_timestamp` (step N-1 and N timestamps) (`paths_query_runner.py:180-199`).
So paths reuses the funnel actors query wholesale — actor set *and* per-actor step timestamps come from the UDF pipeline.

**"View funnel" from a path (v1 and v2 scenes)** is far weaker:
`viewPathToFunnel` (`frontend/src/scenes/paths/pathsDataLogic.ts:239-262`; paths-v2 duplicate at `frontend/src/scenes/paths-v2/pathsDataLogic.ts:213-236`, importing the same helper) walks the clicked node's ancestor chain via `buildFunnelEventsFromPathNode` (`paths/pathsDataLogic.ts:38-63`) — each path item becomes an `EventsNode` (pageview URLs become `$pageview` + `$current_url` exact-match) — and opens a **new** funnel insight carrying only `dateRange.date_from`.
It sets no `funnelOrderType`, no window, no exclusions: the resulting funnel is default *ordered* with a *14-day* window, so its numbers do not (and today are not expected to) match the path edge counts.

## 5. Reusable units for a paths query

- **Event-source construction**: `FunnelEventQuery` (`funnel_event_query.py:69`) — date range (`:631`), sampling (`:611`), entity prefilter (`:655`), property/test-account filters (`:701`; `insights/utils/properties.py:59`), aggregation-target resolution incl. groups and HogQL (`:583`), data-warehouse/mixed-table unions (`:108-185`).
- **Entity → boolean expr**: `FunnelEventQuery._build_step_query` (`funnel_event_query.py:349-410`), built on `action_to_expr` / `property_to_expr` (`posthog/hogql/property.py`); note the separate retention-flavored `entity_to_expr` (`posthog/hogql/property.py:1369`) used by paths v1's start/end-point logic.
- **Window/interval helpers**: `funnel_window_interval_unit_to_sql` (`funnels/utils.py:26-44`), `FunnelUDF.conversion_window_limit` (`funnel.py:75-78`), `QueryDateRange` (`posthog/hogql_queries/utils/query_date_range.py:150`), interval helpers `get_start_of_interval_hogql` (`insights/utils/utils.py`, used at `funnel_trends.py:181`).
- **Defaults/context**: `FunnelQueryContext` (`funnel_query_context.py:24`) — window default 14/day (`:113-119`), breakdown boxing (`:64-95`), `max_steps` (`:121-125`).
- **UDF invocation scaffolding**: `FunnelUDF._inner_aggregation_query` (`funnel.py:115-206`), `event_array_filter` payload trimming (`funnel.py:96-111`), UDF registry + version suffixing (`posthog/hogql/functions/udfs.py:5-41`, `posthog/udf_versioner.py:12`), XML definitions (`posthog/user_scripts/v12/user_defined_function.xml`), Rust source (`funnel-udf/src/`).
- **Actor resolution**: `FunnelsQueryRunner.to_actors_query` (`funnels_query_runner.py:132-140`), `FunnelUDF.actor_query` (`funnel.py:432-454`), `InsightActorsQueryRunner` dispatch (`insight_actors_query_runner.py:86-89`), `ActorsQueryRunner` person hydration (`actors_query_runner.py:38`); paths already consumes this stack (`paths_query_runner.py:243-261`).
- **Aggregation ops**: `FirstTimeForUserAggregationQuery` (`funnel_aggregation_operations.py:13`).
- **Compare machinery**: `_run_in_parallel` + previous-period context cloning (`funnels_query_runner.py:323-372, 584-611`).
- **Validation pattern**: `QueryValidationRule` classes (`funnel_validation_rules.py:11-150`, wired at `funnels_query_runner.py:103-110`).
- **Test fixtures/patterns**: `journeys_for` declarative event seeding (`posthog/test/test_journeys.py:22`); factory-based suites parameterized by order type — `funnel_breakdown_test_factory` / `assert_funnel_results_equal` (`funnels/test/breakdown_cases.py:60`), `funnel_conversion_time_test_factory` (`funnels/test/conversion_time_cases.py`); `ClickhouseTestMixin` + `snapshot_clickhouse_queries` (`posthog/test/base.py`, used throughout `funnels/test/test_funnel.py:1-80`); per-mode files (`test_funnel_strict.py`, `test_funnel_unordered.py`, `test_funnel_persons.py`); UDF-level Rust e2e tests in `funnel-udf/src/e2e_tests.rs`.

## 6. Feasibility facts for "path A→B == some funnel"

**What a strict 2-step funnel counts exactly**: unique aggregation targets (persons by default) having *some* event matching A, followed — with **no event of any kind in between** (all events are fed in, `funnel.py:116-119`; any non-matching event resets progress, `steps.rs:331-337`) — by an event matching B, where B's timestamp is within `conversion_window` of that A (`steps.rs:254-256`), and **both events fall inside the query date range** (`funnel_event_query.py:631-645`).
Each actor counts once regardless of how many qualifying A→B pairs they have (single best-attempt result per actor, `steps.rs:196-229`, plus early exit on completion `steps.rs:190-194`).
An ordered (default) funnel differs by tolerating intervening events.

**Differences vs per-session transition counting** (draft paths-v2: events → arrays → `arraySplit` on inactivity → optional consecutive-dedupe → per-step transition counts):

1. *Multiplicity*: funnel = 1 per actor; paths = 1 per qualifying session (actor with 3 sessions counts 3).
2. *Windowing*: funnel window is a fixed span anchored at the step-1 event; paths sessions are gap-based (inactivity split), unbounded total length.
3. *Adjacency universe*: strict funnels treat **every** team event as a potential sequence breaker, while a paths edge A→B means B was the next *displayed path item* (post include/exclude filters, cleaning, dedupe) — a strict funnel undercounts whenever excluded/filtered events sit between A and B, and an ordered funnel overcounts by ignoring intermediates entirely.
4. *Dedupe*: paths' consecutive-dedupe (A,A,B → A→B) has no funnel equivalent; repeated identical steps in funnels instead require strictly increasing timestamps (`base.py:527-530`, `is_equal`/`is_superset` at `insights/utils/entities.py:45,125`).
5. *Date range*: both A and B must be in range for funnels; a session-based split can straddle the boundary.

**Could the UDF emit per-step sequences for a paths result?**
Partially — the steps mode already returns, per actor, the matched event UUID array per step plus inter-step timings for the best attempt (`Array(Array(UUID))` + `Array(Float64)` in the v12 return type; consumed for recordings/timestamps at `funnel.py:80-88, 398-430`), so one canonical step sequence per actor is recoverable and joinable back to events by UUID.
But **no mode returns all attempts**: `loop_prop_val` pushes exactly one `Result` per prop_val (`steps.rs:219-229`) and stops scanning after the first completion (`steps.rs:190-194`).
The trends variant (`aggregate_funnel_trends_v12`, return `Array(Tuple(UInt64 entrance_period_start, Int8 success_bool, Nullable(String), UUID))`; invoked at `funnel_trends.py:187-199`) is the closest to "per entry" semantics — one row per actor per *entrance interval* ("a person is counted at most once in each entrance period", `funnel_trends.py:37-39`) — still not per-session and without per-step detail.
`funnel_order_type` is a free String argument, so a new mode (e.g. "all attempts" / "per session") is an additive UDF change, but it requires the versioned build-and-deploy dance: bump `posthog/udf_versioner.py`, ship binaries under `posthog/user_scripts/vN/`, deploy to ClickHouse, then flip `UDF_VERSION` (`funnel-udf/README.md:11-22`).

**Known constraints**:
per-actor event arrays are materialized in ClickHouse memory before crossing the UDF boundary — mitigated by the `event_array_filter` heuristic (`funnel.py:91-95`) and `max_bytes_before_external_group_by` (`funnels_query_runner.py:297-300`);
matched-event UUIDs capped at 10 per step (`steps.rs:60`);
`steps_bitfield` is `UInt32` (≤32 steps) and step indices ride in `Array(Int8)`/`Int8` (≤127); `num_steps` is `UInt8`;
funnels require ≥2 steps (`funnel_validation_rules.py:11-18`);
UDF processes are pooled (`executable_pool`, `lifetime 600`, RowBinary framing — v12 XML; `funnel-udf/src/main.rs:104-141`);
the UDF was rewritten from Python to Rust because Python's GC crashed ClickHouse nodes under load (`funnel-udf/README.md:26`).

## 7. Code location and import-direction constraints

Funnels live in core: `posthog/hogql_queries/insights/funnels/` (plus `posthog/hogql/functions/udfs.py`, `posthog/user_scripts/`, `funnel-udf/`).
Paths live in a product: `products/product_analytics/backend/hogql_queries/paths/paths_query_runner.py`.

Both import directions exist today and are sanctioned by tach:
`products.product_analytics` declares `depends_on = ["posthog", …]` (`tach.toml:551-562`), and `posthog` declares `depends_on = [... "products.product_analytics" ...]` (`tach.toml:81-137`) — so the paths runner freely imports `FunnelsQueryRunner` and funnel utils (`paths_query_runner.py:35-36`), while core's `insight_actors_query_runner.py:37` imports the paths runner back.
Caveat: that mutual dependency already forces a deferred inline import of `InsightActorsQueryRunner` inside `funnel_join` to dodge a circular import (`paths_query_runner.py:235`).

`product_analytics` is **not** an isolated product (no `backend:contract-check` script in `products/product_analytics/package.json`), so facade enforcement doesn't apply to it yet; the repo convention (`.claude/rules/product-isolation.md`, `products/architecture.md:86-97, 423`) treats `backend/hogql_queries/` as an approved *wiring location* whose classes may implement the core-owned `QueryRunner` base and be registered/driven by core.
Practical implication for a shared paths/funnels layer: shared computation primitives (event query, UDF scaffolding, window helpers) belong in core (`posthog/hogql_queries/insights/funnels/` or a new `posthog/hogql_queries/insights/utils/` module), which both core funnels and the product-owned paths runner may import; putting shared code under `products/product_analytics/` and importing it from core funnels would deepen the existing cycle and break once the product isolates.
