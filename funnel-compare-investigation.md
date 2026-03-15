# Investigation: Funnel Insights — Period-over-Period Comparison

## Problem

Users need to compare funnel conversion rates between two time periods (e.g., week-over-week, month-over-month) to track performance changes.
Currently they resort to HogQL workarounds like `toString(toISOWeek(timestamp))` breakdowns.

PostHog already has a "Compare to previous period" feature for Trends, Stickiness, and Web Analytics insights.
Funnels do not support it.

## Existing Compare Pattern (Trends)

The compare feature follows this flow:

### Schema (source of truth)

**TypeScript** — `frontend/src/queries/schema/schema-general.ts:1357-1375`:
```ts
export interface TrendsQuery extends InsightsQueryBase<TrendsQueryResponse> {
    // ...
    compareFilter?: CompareFilter
}
```

**CompareFilter** — `frontend/src/queries/schema/schema-general.ts`:
```ts
export type CompareFilter = {
    compare?: boolean
    compare_to?: string  // e.g. "-1y", "-14d", "-100w"
}
```

**Python** (generated) — `posthog/schema.py:16244`:
```python
compareFilter: CompareFilter | None = Field(default=None, description="Compare to date range")
```

### Backend (Trends)

**`posthog/hogql_queries/insights/trends/trends_query_runner.py`**:

1. **`setup_series()`** (line 813): When `compareFilter.compare` is `True`, duplicates every series into a "current" and "previous" variant using `SeriesWithExtras(is_previous_period_series=True/False)`
2. **`to_queries()`** (line 147): For previous-period series, uses `query_previous_date_range` instead of `query_date_range` to build the SQL query with shifted dates
3. **`query_previous_date_range`** (line 696): Returns either `QueryCompareToDateRange` (custom offset like `-1m`) or `QueryPreviousPeriodDateRange` (automatic previous period)
4. **Result formatting** (line 598): Adds `compare=True` and `compare_label="current"|"previous"` to each series result object

### Frontend (Trends)

1. **`insightVizDataLogic.ts:193`** — `supportsCompare` selector determines which insight types show the toggle
2. **`queries/utils.ts:349`** — `isInsightQueryWithCompare()` type guard lists which queries have `compareFilter`
3. **`InsightDisplayConfig.tsx:80-83`** — `showCompare` variable controls rendering the `<CompareFilter>` component
4. **`CompareFilter.tsx`** — Dropdown with "No comparison", "Compare to previous period", "Compare to X earlier"
5. **Visualization** — Previous-period series rendered at 50% opacity alongside current series

## Proposed Changes for Funnels

### Scope Decision: Which Funnel Viz Types?

FunnelVizType has four values:
- **`Steps`** (default) — Bar chart showing step-by-step conversion. **Best candidate for compare.** Could show side-by-side bars or a summary table.
- **`Trends`** — Line graph of conversion rate over time. **Natural fit for compare** since it already uses the `LineGraph` component (same as Trends).
- **`TimeToConvert`** — Histogram of time distributions. Compare is conceptually possible but visualization is complex.
- **`Flow`** — ReactFlow graph visualization. Compare doesn't map well here.

**Recommendation**: Start with `Trends` funnel viz type only, since it already uses the same line graph infrastructure as Trends and the compare pattern maps directly.
`Steps` is a good second phase.
`TimeToConvert` and `Flow` should be excluded.

### 1. Schema Changes

**File: `frontend/src/queries/schema/schema-general.ts`**

Add `compareFilter` to `FunnelsQuery`:

```ts
export interface FunnelsQuery extends InsightsQueryBase<FunnelsQueryResponse> {
    kind: NodeKind.FunnelsQuery
    interval?: IntervalType
    series: (AnyEntityNode | GroupNode)[]
    funnelsFilter?: FunnelsFilter
    breakdownFilter?: BreakdownFilter
    compareFilter?: CompareFilter  // <-- NEW
}
```

Then regenerate `posthog/schema.py` (the Python schema is auto-generated from TS).

### 2. Backend Changes

**File: `posthog/hogql_queries/insights/funnels/funnels_query_runner.py`**

The funnel query runner is simpler than trends — it doesn't have a series duplication mechanism.
For `FunnelVizType.Trends` (funnel trends), the approach would be:

1. Add `query_previous_date_range` property (same pattern as trends runner)
2. In `_calculate()`, when `compareFilter.compare` is True and viz type is `Trends`:
   - Execute the query once for the current period (existing code)
   - Create a modified `FunnelQueryContext` with shifted date range for the previous period
   - Execute the query again
   - Merge results, tagging each with `compare_label`
3. Return both result sets in the response

**Key files to modify:**
- `funnels_query_runner.py` — main runner, add compare logic
- `funnel_query_context.py` — may need to accept overridden date range

**Date range utilities (already exist):**
- `posthog/hogql_queries/utils/query_previous_period_date_range.py`
- `posthog/hogql_queries/utils/query_compare_to_date_range.py`

### 3. Frontend Changes

#### Type Guards

**File: `frontend/src/queries/utils.ts:349`**

Add `FunnelsQuery` to `isInsightQueryWithCompare`:
```ts
export function isInsightQueryWithCompare(
    node?: Record<string, any> | null
): node is TrendsQuery | StickinessQuery | WebStatsTableQuery | WebOverviewQuery | FunnelsQuery {
    return isTrendsQuery(node) || isStickinessQuery(node) || isWebStatsTableQuery(node) || isWebOverviewQuery(node) || isFunnelsQuery(node)
}
```

#### Compare Toggle Visibility

**File: `frontend/src/scenes/insights/insightVizDataLogic.ts:193`**

Update `supportsCompare` to include funnels (possibly restricted to `FunnelVizType.Trends`):
```ts
supportsCompare: [
    (s) => [s.querySource, s.display, s.dateRange, s.funnelsFilter],
    (q, display, dateRange, funnelsFilter) =>
        ((isTrendsQuery(q) || isStickinessQuery(q) || isWebAnalyticsInsightQuery(q)) &&
            display !== ChartDisplayType.WorldMap &&
            display !== ChartDisplayType.CalendarHeatmap &&
            dateRange?.date_from !== 'all') ||
        (isFunnelsQuery(q) && funnelsFilter?.funnelVizType === FunnelVizType.Trends &&
            dateRange?.date_from !== 'all'),
],
```

**File: `frontend/src/queries/nodes/InsightViz/InsightDisplayConfig.tsx:80`**

Update `showCompare` to include funnel trends:
```ts
const showCompare =
    (isTrends && display !== ChartDisplayType.ActionsAreaGraph && display !== ChartDisplayType.CalendarHeatmap) ||
    isStickiness ||
    isTrendsFunnel ||  // <-- NEW
    isWebAnalyticsInsightQuery(querySource)
```

#### Visualization

**File: `frontend/src/scenes/funnels/FunnelLineGraph.tsx`**

The `FunnelLineGraph` already uses the same `LineGraph` component as Trends.
If the backend returns results with `compare_label` metadata, the line graph component should handle it the same way Trends does — previous period at 50% opacity.

Need to verify that `indexedSteps` (from `funnelDataLogic`) properly passes through `compare` and `compare_label` fields from the result data.

**File: `frontend/src/scenes/funnels/funnelDataLogic.ts`**

The `results` selector (line 234) would need to handle compare results.
For funnel trends, results are `TrendResult[]`-like objects with `labels`, `data`, `days` fields.
The compare feature would double these, adding `compare_label` to each.

### 4. Test Changes

**Backend tests:**
- `posthog/hogql_queries/insights/funnels/test/test_funnel_trends.py` — Add tests for compare with funnel trends

**Frontend tests:**
- `frontend/src/scenes/funnels/funnelDataLogic.test.ts` — Add test cases for compare results processing

## Complexity Assessment

### Low Complexity (recommended Phase 1)
- Schema change: Add `compareFilter` to `FunnelsQuery` — trivial
- Frontend toggles: Update type guards + show compare for funnel trends — straightforward
- Backend for funnel trends: Execute query twice with different date ranges — moderate

### Medium Complexity (Phase 2)
- Steps funnel compare: Side-by-side bars showing current vs previous conversion rates per step
- Requires new visualization components or significant modifications to `FunnelBarVertical`/`FunnelBarHorizontal`

### High Complexity (not recommended)
- TimeToConvert comparison: Overlaid histograms
- Flow comparison: No clear visualization approach

## Estimated Effort

Phase 1 (Funnel Trends compare):
- Schema + Python codegen: 1 file change + regeneration
- Backend runner: ~100 lines of new code in `funnels_query_runner.py`
- Frontend type guards + toggle: ~10 lines across 3 files
- Frontend visualization: Minimal if line graph already handles compare_label
- Tests: ~2-3 new test methods
- **Total: ~8-12 files modified**

## Risks & Considerations

1. **Cache key invalidation**: Adding `compareFilter` to the query changes cache keys. Need to ensure caching layer handles this properly (likely automatic since it's part of the query object).

2. **Performance**: Executing two funnel queries (current + previous) doubles query time. Funnel queries can be expensive. Consider:
   - Parallel execution of both queries
   - Adding a note about increased query time in the UI

3. **Funnel conversion window edge case**: The conversion window (`funnelWindowInterval`) interacts with the date range. For the previous period, users who enter the funnel near the end of the previous period might not have their full conversion window. This is the same issue described in the related GitHub issue about funnel date filtering logic.

4. **Breakdown + Compare interaction**: When both breakdown and compare are active, the result set multiplies (breakdowns x 2 periods). Need to test this carefully and consider UI implications.

5. **Schema migration**: Since schema.py is auto-generated from the TypeScript schema, this needs the standard schema generation process (`pnpm run schema:build` or similar).
