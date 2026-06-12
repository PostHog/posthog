# TrendsQuery

`TrendsQuery` shows how event and action counts change over time.
It takes a list of `series` (events, actions, or data warehouse entities, each with an aggregation "math"), an `interval` (`hour`/`day`/`week`/`month`), an optional `breakdownFilter`, an optional `compareFilter`, and a `trendsFilter` with display options.
It is the most general-purpose insight kind and powers most dashboard tiles.

## Rendering

`TrendsQuery` is an insight _source_, not a standalone renderable node.
Wrap it in an `InsightVizNode` and pass that to `<Query />`:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'
import { NodeKind } from '@posthog/query-frontend/schema/schema-general'

;<Query
  query={{
    kind: NodeKind.InsightVizNode,
    source: {
      kind: NodeKind.TrendsQuery,
      interval: 'day',
      dateRange: { date_from: '-7d' },
      series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview', math: 'total' }],
      trendsFilter: { display: 'ActionsLineGraph' },
    },
  }}
/>
```

See `InsightTrendsQuery` in `../../examples.ts` for a fuller example with properties and a breakdown.

## Display modes

The chart type is chosen via `trendsFilter.display` (a `ChartDisplayType`).
`Trends.tsx` (`TrendInsight`) switches on it:

- `ActionsLineGraph` (default), `ActionsLineGraphCumulative`, `ActionsAreaGraph`, `ActionsBar`, `ActionsUnstackedBar` → `viz/ActionsLineGraph.tsx`
- `ActionsBarValue` → `viz/ActionsHorizontalBar.tsx`
- `ActionsPie` → `viz/ActionsPie.tsx`
- `BoldNumber` → `BoldNumber` from `@posthog/visualizations`
- `ActionsTable` → `../InsightViz/views/InsightsTable/InsightsTable.tsx`
- `WorldMap` → `WorldMap` / `RegionMap` from `@posthog/visualizations` (region map when broken down by `$geoip_subdivision_1_*`)
- `CalendarHeatmap` → `TrendsCalendarHeatMap` from `@posthog/visualizations`
- `BoxPlot` → `BoxPlotChart` from `@posthog/visualizations`

## Key files

- `Trends.tsx` — `TrendInsight`, the top-level component; picks the viz for the current display mode and renders the "load more breakdown values" CTA.
- `trendsDataLogic.ts` — kea logic keyed by `InsightLogicProps`. Connects to `insightVizDataLogic` and derives render-ready state: `results`/`indexedResults` (sorted, lifecycle-ordered, with series indexes), result customizations (colors, hidden series), `hasBreakdownMore`, `hasPersonsModal`, fractional-number detection, and breakdown update actions.
- `viz/` — the trends-specific chart wrappers listed above, plus `datasetToActorsQuery.ts`, which turns a clicked data point into an `InsightActorsQuery` for the persons modal (`../../persons-modal/`).
- `types.ts` — `IndexedTrendResult` and friends.

The kea logics here are an internal implementation detail of the `<Query />` tag.
Consumers pass `query`/`setQuery` props to `<Query />` and should not bind `trendsDataLogic` directly.

## Shared with other query kinds

The actual chart surfaces (`LineGraph`, `PieChart`, `BoldNumber`, `WorldMap`, etc.) live in the `@posthog/visualizations` package (`common/visualizations/`); this folder only adapts trends responses into their props.

`StickinessQuery` and `LifecycleQuery` reuse the trends viz components: `../InsightViz/InsightVizDisplay.tsx` renders `<TrendInsight view={InsightType.STICKINESS} />` / `<TrendInsight view={InsightType.LIFECYCLE} />` for those kinds, and `trendsDataLogic` exposes `isStickiness`/`isLifecycle` flags to adjust behavior.
