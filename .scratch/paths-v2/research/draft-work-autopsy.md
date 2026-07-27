# Paths v2 draft work autopsy (PR #29364 and friends)

**TL;DR:**
Draft PR [#29364](https://github.com/PostHog/posthog/pull/29364) (branch `paths-v2-separation`, tip `8cbbcfdc`, opened 2025-02-28, closed unmerged, 81 commits, last real work 2025-09-04 plus a master merge 2025-11-06) adds a genuinely separate `PathsV2Query` insight kind end to end: a 5-field `PathsV2Filter` schema, a fully staged HogQL array-pipeline runner (session split, consecutive dedupe, dropoffs, per-step top-N with an "other" bucket), and full insight-type plumbing on the frontend (new `InsightType.PATHS_V2` gated by flag `paths-v2`).
The core pipeline is done and tested; start/end-point trimming, "group events by", persons modal, summaries, and the v1→v2 migration are half-done or absent, and the tip itself doesn't compile (dangling scene imports from the last merge) with several backend tests stale against the tip code.
Master has since moved in ways that fight a naive rebase on nearly every file the PR touches: the v1 paths runner moved to `products/product_analytics/` (PR #58954), the schema codegen grew enum-splitting post-processing, the `paths-v2` feature flag was renamed and re-purposed to swap in the (v1-consuming) `frontend/src/scenes/paths-v2/` viz that master ships today, `d3-sankey` was vendored, EditorFilters changed shape, and kea typegen moved to inline types.

## 1. Schema at the draft tip

`PathsV2` exists only on the branch — master has no `PathsV2` anywhere in `frontend/src/queries/schema/schema-general.ts` or `posthog/schema.py` (grep returns nothing).

From `frontend/src/queries/schema/schema-general.ts@8cbbcfdc` lines 1476–1504 (Pydantic mirror in `posthog/schema.py@8cbbcfdc:4563-4571, 14410-14456, 2273-2280, 9921-9943`):

```ts
export type PathsV2Item = {
    step_index: number
    source_step: string | null
    target_step: string | null
    value: number
}
export interface PathsV2QueryResponse extends AnalyticsQueryResponseBase<PathsV2Item[]> {}
export type CachedPathsV2QueryResponse = CachedQueryResponse<PathsV2QueryResponse>

export type PathsV2Filter = {
    /** @default 5 */  maxSteps?: integer
    /** @default 3 */  maxRowsPerStep?: integer
    /** @default 14 */ windowInterval?: integer
    /** @default day */ windowIntervalUnit?: ConversionWindowIntervalUnit
    /** @default false */ collapseEvents?: boolean
}
export interface PathsV2Query extends InsightsQueryBase<PathsV2QueryResponse> {
    kind: NodeKind.PathsV2Query
    series?: AnyEntityNode[]        // intended start/end points, max 2 (entitiesLimit=2 in the UI)
    pathsV2Filter?: PathsV2Filter
}
```

Notes:

- `ConversionWindowIntervalUnit` (second/minute/hour/day/week/month) is a **new enum the PR adds to `frontend/src/types.ts`** (PR diff hunk at `frontend/src/types.ts` adds it next to `PathsV2FilterType {}`); it does not exist on master (master funnels use `FunnelConversionWindowTimeUnit`).
- Via `InsightsQueryBase`, `PathsV2Query` also accepts `dateRange`, `properties`, `filterTestAccounts` (default `False`), `samplingFactor`, `aggregation_group_type_index`, `dataColorTheme` (`posthog/schema.py@8cbbcfdc:14410-14456`); the runner only uses the first three — sampling and group aggregation are accepted but ignored.
- `NodeKind.PathsV2Query` is added to `NodeKind`, `QuerySchema`, `InsightQueryNode`, `InsightFilterProperty` (`'pathsV2Filter'`), `InsightFilter`, and a `FileSystemIconType` `'insight/pathsV2'` (PR diff, schema-general.ts hunk).
- Backend registration: `get_query_runner` branch for `"PathsV2Query"` (`posthog/hogql_queries/query_runner.py@8cbbcfdc:255-259`), plus `PathsV2Query` in the insight-query unions of `posthog/types.py@8cbbcfdc:49` and `posthog/schema_helpers.py@8cbbcfdc:51,147` (`filter_key_for_query` → `"pathsV2Filter"`).

## 2. The draft runner, stage by stage

`posthog/hogql_queries/insights/paths_v2/paths_v2_query_runner.py@8cbbcfdc` (451 lines).
`PathsV2QueryRunner(AnalyticsQueryRunner[PathsV2QueryResponse])` at line 24; constants `POSTHOG_OTHER = "$$__posthog_other__$$"`, `POSTHOG_DROPOFF = "$$__posthog_dropoff__$$"` at lines 20–21.
Each stage is a HogQL `parse_select` subquery nesting the previous one, with docstrings containing worked example tables.

1. **`_event_base_query` (L111)** — `SELECT timestamp, person_id as actor_id, coalesce({path_item}, '$$__posthog_null__$$') as path_item FROM events ... ORDER BY actor_id, timestamp`, with date-range, `properties`, and `filterTestAccounts` filters ANDed into the WHERE.
   The path item is **hard-coded** to `apply_path_cleaning(properties.$pathname)` with `ast.Field(chain=["event"])` left commented out (L175-177) — "group events by" is not wired.
   When `query.series` is set it appends a `series_entities_flags` tuple column of per-entity boolean exprs built by the (new) `entity_to_expr` helper; otherwise a `tuple(NULL, NULL)` placeholder (L180-196).
2. **`_paths_per_actor_as_array_query` (L199)** — `groupArray(timestamp)`, `groupArray(path_item)`, `groupArray(series_entities_flags)` per `actor_id`; contains a commented-out variant that only added the flags array conditionally (L226-232).
3. **`_paths_per_actor_and_session_as_tuple_query` (L236)** — the heart:
   - `arrayZip(timestamp_array, path_item_array, arrayPopBack(arrayPushFront(timestamp_array, NULL)), series_entities_flags_array)` → tuples of (ts, item, prev_ts, flags);
   - **session split**: `arraySplit(x -> if(x.1 < x.3 + {session_interval}, 0, 1), paths_array)` with `session_interval = toInterval<Unit>(windowInterval)` (L274-275), then `ARRAY JOIN` with `session_index`;
   - `arrayMap` drops the prev-ts column (L277-278);
   - **consecutive dedupe** (`collapseEvents`): `arrayFilter((x, i) -> i = 1 OR x.2 != arrayElement(..., i - 1).2, ...)` (L280-285), selected via a placeholder alias only when `collapseEvents` is true (L307-312);
   - **start/end trimming (WIP)**: `arrayFirstIndex(x -> x.3.1 = 1, ...)` / `arrayLastIndex(x -> x.3.2 = 1, ...) - 1` when 1 or 2 series entities exist, else `1`/`null`, then `arraySlice(arr, start_index, end_index)` (L287-290) — note `arraySlice`'s third argument is a *length*, not an end index, and the code is f-string-conditional on `len(series)`;
   - **dropoff append**: `arrayPushBack(..., (now(), '$$__posthog_dropoff__$$', tuple(null[, null])))` (L292-293);
   - **maxSteps slice**: `arraySlice(..., 1, {max_steps})` (L295-296).
4. **`_paths_flattened_with_previous_item` (L316)** — `ARRAY JOIN` the per-session tuple array with `step_in_session_index`, adding `previous_path_item` via `arrayElement(..., i - 1).2`.
5. **`_paths_top_nodes_grouped` (L359)** — CTE `paths` = `COUNT(*)` grouped by (step, source, target); CTE `top_n_targets` = `ROW_NUMBER() OVER (PARTITION BY step_index ORDER BY SUM(value) DESC)` filtered to `rn <= {max_rows_per_step}` and excluding dropoffs; outer SELECT LEFT-JOINs both source (`step_index - 1`) and target against `top_n_targets` and CASE-replaces misses with `$$__posthog_other__$$`, always keeping dropoffs and NULL sources ("path start") (L401-427).
6. **`to_query` (L436)** — final aggregation: `step_index - 1 AS step_index`, `sum(value)`, `WHERE step_index > 0` (drops the synthetic step-0/path-start row), `ORDER BY step_index, value DESC`.
7. **`_calculate` (L83)** — runs `execute_hogql_query`, maps rows into `PathsV2Item`s, and re-sorts within each step: real targets by value desc, then "other", then dropoff (L93-105).

Defaults come from `PathsV2Filter.model_fields[...].default` via `@property` accessors (L28-72).
`posthog/hogql_queries/insights/paths_v2/utils.py@8cbbcfdc` maps interval units to SQL and contains a real bug: month maps to `"toInvervalMonth"` (typo — invalid function name).

**Finished:** date/property/test-account filters, session window, collapse, dropoffs, maxSteps, per-step top-N + "other", final aggregation and sorting — all matching PR-body checkmarks and covered by tests (see §5).
**Half-done at the tip:** start/end-point trimming (flag columns exist, trimming expressions questionable, all related tests skipped or hollow; the newer `paths-v2-base` branch tip `ce5106d4` — "remove more start and end event handling", 2025-09-04 — strips the flags machinery *and* `apply_path_cleaning` back out, see `git diff 8cbbcfdc ce5106d4 -- posthog/.../paths_v2_query_runner.py`); configurable path item (commented-out `event` alternative); two commented-out code blocks; the month-interval typo; `samplingFactor`/group aggregation ignored.

Also touched: the PR **adds** `entity_to_expr(entity: EntityNode, team: Team)` to `posthog/hogql_queries/insights/utils/entities.py@8cbbcfdc:106` (plus tests in `utils/test/test_entities.py`) — this generic helper never merged and does not exist on master's `entities.py`.

## 3. Frontend inventory at the draft tip

Scene (`frontend/src/scenes/paths-v2/` at `8cbbcfdc`):

- **`pathsV2DataLogic.ts`** — kea logic connected to `insightVizDataLogic`; selector `results` runs `convertToLegacyPaths` which maps `PathsV2Item[]` into v1 `PathsLink[]` by prefixing names as `${step_index}_${source_step}` / `${step_index + 1}_${target_step}` ("so that I don't have to rewrite the frontend immediately", per its comment), `average_conversion_time: 0`; selector `paths` derives typed nodes (`Node`/`Dropoff`/`Other` from the sentinel strings) plus `step_index` parsed off the prefix.
- **`renderPathsV2.ts`** — d3 + `d3-sankey` renderer: `sankeyLeft` alignment, rounded nodes, node color CSS vars for regular/other/dropoff, recursive upstream/downstream link highlighting on hover, canvas width scaling by max step. **Contains a duplicated `import { PathNodeData, PathTargetLink } ...` block (merge artifact) — the file does not compile as-is.**
- **`PathsV2.tsx`** — component wiring resize observer + render loop + theme CSS vars; **still renders a `DebugPathTable`** (raw tailwind-gray table of the response) above the viz.
- **`PathV2NodeLabel.tsx`** — absolute-positioned label with name ("Dropped off" / "Other (i.e. all remaining values)" for sentinels) and a count button whose `openModal` handler is an **empty no-op** (persons modal not implemented).
- **`constants.ts`** — the two sentinel strings; **`types.ts`** — `PathNodeType` enum + `Paths`/`PathsNode` types; **`pathUtils.ts`** — trimmed copy of the v1 helpers.
- Leftovers from the 2025-11-06 master merge: `pathsDataLogic.ts` and `PathNodeLabel.tsx` (master's v1-consuming versions) are still present; `PathNodeLabel.tsx` imports `./renderPaths`, **which doesn't exist at this sha** (renamed to `renderPathsV2.ts`), so the tip tree is broken.

Editor filters (`frontend/src/scenes/insights/EditorFilters/` at `8cbbcfdc`):

- **`PathsV2Steps.tsx`** — `ActionFilter` bound to `query.series` (`entitiesLimit={2}`, math disabled) for start/end points, plus a "Remove repeated events" `LemonCheckbox` for `collapseEvents`. Full of commented-out scaffolding and a `console.debug`.
- **`PathsV2SessionWindow.tsx`** — conversion-window control (number + unit select, bounds per unit) forked from the funnels one, properly wired to `windowInterval`/`windowIntervalUnit` via `updateInsightFilter`.
- **`PathsV2GroupEventsBy.tsx`** — "Expand events by" UI mock: local `useState` only, hard-coded `$pageview`/`$browser`, `console.debug`s, **not wired to the query at all**.
- **`PathsV2MaxStepPicker.tsx` / `PathsV2MaxRowsPerStepPicker.tsx`** (`frontend/src/queries/nodes/InsightViz/`) — `LemonSelect`s (2–20) updating `maxSteps`/`maxRowsPerStep`; both functional. Mounted in `InsightDisplayConfig.tsx@8cbbcfdc:347-350`.

Registration (all at `8cbbcfdc`):

- `EditorFilters.tsx:186-190` — `isPathsV2` adds groups Steps / Session Window / "Expand events by".
- `insightNavLogic.tsx:189-197` — "Event Journeys" tab, shown when `FEATURE_FLAGS.PATHS_V2` or the view is already active.
- `defaults.ts:85-96` — `pathsV2QueryDefault` with an "All events" series and empty `pathsV2Filter`.
- `insightVizDataLogic.ts:165,246,716` — `isPathsV2` + `pathsV2Filter` selectors; date-range side-effect opt-out.
- `InsightVizDisplay.tsx:184-185` — `case InsightType.PATHS_V2: return <PathsV2 />`; **it also reverts `case InsightType.PATHS` to always `<Paths />` and deletes `isUsingPathsV1/isUsingPathsV2` from `insightLogic`** (PR diff) — i.e. it undoes master's flag-swap approach.
- `InsightViz.tsx` — paths v2 uses the horizontal editor layout.
- Saved insights: `SavedInsights.tsx:130-135,544` metadata ("Event Journeys"); `SavedInsightsFilters.tsx:30-35` and `newInsightsMenu.tsx:19` hide the type without the flag.
- `queries/utils.ts:295-296,357,555` — `isPathsV2Query`, membership in `isInsightQueryNode`, `nodeKindToFilterProperty`.
- `filtersToQueryNode.ts:79`, `queryNodeToFilter.ts:120,130`, `sharedUtils.ts:66-68` (`isPathsV2Filter`), `types.ts:2488,2707` (`InsightType.PATHS_V2`, empty `PathsV2FilterType`), `summarizeInsight.ts:216-218` (returns `''`, TODO), `InsightDetails.tsx:277-280` (`PathsV2Summary` stub), `tileLayouts.ts:62` (full-width dashboards), `manifest.tsx:140-146` ("Insight/Event journeys" tree entry), `constants.tsx:228,367` (`FEATURE_FLAGS.PATHS_V2 = 'paths-v2'`, `INSIGHT_VISUAL_ORDER.pathsV2 = 41`), `defaultTree.tsx` + `base.scss` (icon color `--insight-paths-v2-light`).

## 4. PR-body todos vs actual code

| Todo (state in PR body) | Reality in code at `8cbbcfdc` |
| --- | --- |
| ☑ date range / properties / test account filters | Done — runner L137-162, tests exist |
| ☑ session window | Done — `arraySplit` + window fields; **month unit broken by `toInvervalMonth` typo** (`utils.py`) |
| ☑ configurable row limit + group remaining ("other") | Done — `maxRowsPerStep`, `ROW_NUMBER ... rn <= N`, `POSTHOG_OTHER` |
| ☑ configurable col limit | Done — `maxSteps` `arraySlice` |
| ☐ start event support / ☐ end event support | **Partially present anyway**: `series_entities_flags` + `arrayFirstIndex`/`arrayLastIndex` trimming is in the tip runner, but untested (tests skipped), of dubious correctness (`arraySlice` length-vs-index), and the follow-up branch `paths-v2-base` (`ce5106d4`) removes it again |
| ☐ intermediate steps / step orders | Absent |
| ☑ collapsing events | Done — `collapseEvents` + `arrayFilter`, tested |
| ☑ handle start step / dropoffs / remaining / ordering | Done — NULL-source keep, `POSTHOG_DROPOFF` append + keep, `POSTHOG_OTHER`, `_calculate` sort (runner L93-105, 401-427) |
| ☐ expanding properties per event | Only the unwired `PathsV2GroupEventsBy` UI mock; runner hard-codes `$pathname` |
| ☐ excluding steps | Absent |
| ☐ groups "aggregating by..." | Schema accepts `aggregation_group_type_index`; runner ignores it; UI commented out in `PathsV2Steps.tsx` |
| ☐ migration button v1→v2 | Absent (no conversion code anywhere in the diff) |
| ☐ add test cases | **Understated: a 732-line backend test file exists** (see §5), though several tests are stale vs the tip |
| ☐ comments with example data | **Actually done** — every runner stage has an example-table docstring |
| ☐ persons modal | Not done — `PathV2NodeLabel.openModal` is `(): void => {}` |
| ☐ query summary | Not done — `summarizeInsight.ts` returns `''`; `PathsV2Summary` stub |
| ☐ context menu ("view funnel") / funnel→paths v2 | Absent (no menu on `PathV2NodeLabel`) |

## 5. Test coverage at the draft tip

`posthog/hogql_queries/insights/paths_v2/test/test_paths_v2_query_runner.py@8cbbcfdc` (732 lines, `journeys_for` fixtures) + one ClickHouse SQL snapshot (`test_paths_v2_query_runner.ambr`):

- **`TestPathsV2`** (end-to-end `calculate()`): `test_simple_path_query` (4-persona funnel → full transition list incl. dropoffs), `test_aggregates_nodes_exceeding_limit` (maxRowsPerStep=3 → "other" bucketing on both source and target), `test_aggregates_nodes_grouping` (maxRowsPerStep=1), `test_sorts_results` (value desc, then other, then dropoff), `test_collapses_events` (false vs true), and `test_start_and_end_point` — **skipped** ("pending start and end point implementation").
- **`TestPathsV2BaseEventsQuery`**: SQL string assert + column check, date filter, property filter, test-account filter; `test_start_and_end_event` **skipped/`pass`**.
- **`TestPathsV2PathsPerActorAsArrayQuery`**: array aggregation per actor; start/end **skipped/`pass`**.
- **`TestPathsV2PathsPerActorAndSessionAsTupleQuery`**: snapshot of the tuple query, tuple structure, session split across the 14-day window, consecutive-dedupe, dropoff append, maxSteps limiting (default and `maxSteps=2`), and a non-skipped but assertion-light `test_start_and_end_event` (only asserts 1 row; contains a TODO about `collapseEvents` interacting with start/end handling).
- **Staleness:** the expectations predate the tip's start/end work — e.g. `test_event_base_query` expects `event AS path_item` and 3 columns while the tip runner emits path-cleaned `$pathname` plus a 4th flags column (runner L164-196); tuple tests expect 2-tuples where the tip emits 3-tuples; the `.ambr` snapshot matches the pre-flags SQL; `test_event_base_query` also hard-codes `2025-04-03` dates with no `freeze_time`. Several of these tests would fail if run against the tip.
- **Frontend:** `pathsV2DataLogic.test.ts@8cbbcfdc` is the renamed v1 logic test — it still exercises `taxonomicGroupTypes`/`includeEventTypes` (v1 `PathsFilter` concepts) against `pathsV2DataLogic`, which has no such selector; stale. No tests for `renderPathsV2`/components beyond that.

## 6. What master's in-repo `paths-v2` scene does today

Master's `frontend/src/scenes/paths-v2/` is the **merged viz PR [#28495](https://github.com/PostHog/posthog/pull/28495)** (merged 2025-02-25): a visual-only re-skin that still runs the **v1 `PathsQuery`**. File set matches the old `paths-v2` branch tip (`b4bc4c9b`): `PathsV2.tsx`, `PathNodeLabel.tsx`, `pathsDataLogic.ts`, `pathUtils.ts`, `renderPaths.ts`, `Paths.scss`, `types.ts`.

- Selection: `InsightVizDisplay.tsx:383` — `case InsightType.PATHS: return isUsingPathsV2 ? <PathsV2 /> : <Paths />`, driven by `insightLogic.tsx:985-994` selectors on `FEATURE_FLAGS.PRODUCT_ANALYTICS_PATHS_V2` (`constants.tsx:429`, key string still `'paths-v2'`).
- Data: `pathsDataLogic.ts:136-143` — `results` is just `insightData?.result` when `isPathsQuery`; `paths` (L145-162) builds nodes from raw link names. **No result-shape transformation happens in the logic** — the v1 `"<n>_<name>"` step-prefix convention is handled at display time in `pathUtils.ts` via `.replace(/(^[0-9]+_)/, '')` inside `pageUrl()` (lines 84, 96, 116; identical code in v1's `scenes/paths/pathUtils.ts:163-199`).
- Feature parity with v1 kept: persons modal via `pathsFilter.pathStartKey/pathEndKey/pathDropoffKey` (`pathsDataLogic.ts:186-212`), `viewPathToFunnel` (L213-236), node context menu with set-start/set-end/exclude/view-funnel/copy (`PathNodeLabel.tsx:69-91`).
- Differences from v1 (`frontend/src/scenes/paths/`): no `PathNodeCard`/`PathNodeCardButton`/`PathNodeCardMenu`/`PathsLabel`/`pathsInteractionLogic` — replaced by a single `PathNodeLabel` above each node; renderer uses `sankeyLeft` alignment vs v1's `sankeyJustify`, thinner rounded nodes, hover de-emphasis (`renderPaths.ts:7,88` vs `scenes/paths/renderPaths.ts:8,36`); simplified `types.ts` (`PathsNode = { name: string }`).
- Both scenes now import Sankey from the **vendored** `~/vendor/d3/sankey` — `d3-sankey` is no longer in `frontend/package.json` (only `d3` at line 204).

## 7. Divergence: what fights a naive rebase of #29364 onto master

Facts only; every item is a concrete conflict or drift.

1. **v1 paths runner moved to the product folder.** PR [#58954](https://github.com/PostHog/posthog/pull/58954) ("move paths query runner to product_analytics product", merged 2026-05-19) relocated it to `products/product_analytics/backend/hogql_queries/paths/paths_query_runner.py`; `get_query_runner` imports it from there (`posthog/hogql_queries/query_runner.py:471-475` on master). `stickiness` also lives in the product folder; `funnels`, `retention`, `trends`, `lifecycle` remain in `posthog/hogql_queries/insights/`. The draft's `posthog/hogql_queries/insights/paths_v2/` location is therefore inconsistent with where its direct sibling now lives — the structural home for a v2 runner today is `products/product_analytics/backend/hogql_queries/`.
2. **Schema codegen drift.** The pipeline is still `schema-general.ts → schema.json → datamodel-codegen → posthog/schema.py` (`pnpm schema:build` / `hogli build:schema`, `bin/build-schema-python.sh`), but master added post-processing: discriminator patching and `bin/split-schema-enums.py`, which moves all enums into `posthog/schema_enums.py` (imported by `posthog/schema.py:14`). The PR's ~480-line `schema.json` and ~576-line `schema.py` hunks are generated artifacts that cannot be rebased textually — the TS source must be re-applied and everything regenerated. (`hogli build:openapi` is the separate DRF/REST pipeline and is not involved for query nodes, but any new REST surface would go through it.)
3. **`AnalyticsQueryRunner` base-class drift — compatible but not identical.** The subclass contract the draft uses (`query`, `cached_response`, `_calculate()`, `to_query()`, `self.timings/modifiers/limit_context`) is unchanged (master `posthog/hogql_queries/query_runner.py:2403-2416`). But master's `QueryRunner.calculate()` now runs `self.validate()` (validation rules) before `_calculate` (L1401-1410), and `AnalyticsQueryRunner` gained access-control-aware `get_cache_payload` machinery (L2434-2458); `calculate` delegates via `super().calculate()` instead of calling `_calculate` directly as at `8cbbcfdc:1463-1467`. Rebasing the registration hunk into `get_query_runner` is trivial (same pattern at master L471).
4. **Feature-flag and scene collision — the sharpest conflict.** Master renamed the constant to `FEATURE_FLAGS.PRODUCT_ANALYTICS_PATHS_V2` (same `'paths-v2'` key) and uses it to flag-swap the v1-consuming viz (`insightLogic.tsx:985-994`, `InsightVizDisplay.tsx:383`). The draft (a) references the old `FEATURE_FLAGS.PATHS_V2` name in five files, (b) **deletes** `isUsingPathsV1/isUsingPathsV2` and the flag-swap, reverting `InsightType.PATHS` to always render the old `<Paths />`, and (c) rewrites `frontend/src/scenes/paths-v2/` (renames `renderPaths.ts→renderPathsV2.ts`, `Paths.scss→PathsV2.scss`, `pathsDataLogic.test.ts→pathsV2DataLogic.test.ts`, rewrites `types.ts`) into the v2-query viz. Rebasing means deciding whether the shipped v2 viz keeps serving v1 queries; the tip's own unreconciled merge (dangling `./renderPaths` import in `PathNodeLabel.tsx`, orphaned `pathsDataLogic.ts`, duplicate import in `renderPathsV2.ts`) shows this collision was already biting in November.
5. **`d3-sankey` vendored.** `renderPathsV2.ts@8cbbcfdc:2` imports `d3-sankey`; master removed that dependency and both paths scenes import `~/vendor/d3/sankey` (`scenes/paths-v2/renderPaths.ts:7` on master).
6. **Editor-filter registration shape changed.** The draft inserts `...(isPathsV2 ? [{...}] : [])` spreads (`EditorFilters.tsx@8cbbcfdc:186-190`); master's `EditorFilters.tsx` now uses a flat `visibleFilters([...])` list with per-entry `show:` flags (master L149-156). Same for `InsightDisplayConfig` (insertion point still exists, master L~344 area). Mechanical but every hunk needs rewriting.
7. **kea typegen convention.** Master logic files embed generated inline `MakeLogicType` blocks ("Generated by kea-typegen", e.g. master `scenes/paths-v2/pathsDataLogic.ts:43-102`); the draft's `pathsV2DataLogic.ts` uses the old `import type { ... } from './pathsV2DataLogicType'` pattern and needs regeneration.
8. **`entity_to_expr` helper.** The draft's generic `entity_to_expr(EntityNode, Team)` in `entities.py` doesn't exist on master; master's `entities.py` renamed `ExclusionEntityNode`→`FunnelExclusionEntityNode` and added other helpers, and a *different* `entity_to_expr(entity: RetentionEntity, team)` exists at `posthog/hogql/property.py:1369` — re-adding the draft's helper invites a name clash.
9. **Already-landed hunks (no-ops now):** the `ActionFilter.tsx` footer cleanup (master `ActionFilter.tsx:314-330` already matches the PR's version) and the `funnels/base.py` dead-comment deletion (comment already gone on master).
10. **Misc:** `ConversionWindowIntervalUnit` must be re-added to `frontend/src/types.ts` (comes with the branch, no conflict, but the schema build now emits it into `schema_enums.py`); master's `insightNavLogic.tsx` tab list (User Paths at L517) and `manifest.tsx` insight entries (L138 area) still exist as insertion points; `frontend/src/scenes/paths-v2/types.ts` and `pathUtils.ts` are live files on master that the draft rewrites/trims.
