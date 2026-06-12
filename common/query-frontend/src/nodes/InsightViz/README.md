# InsightViz

`InsightVizNode` is the container node for insight queries.
It wraps a single insight query _source_ (`TrendsQuery`, `FunnelsQuery`, `RetentionQuery`, `PathsQuery`, `StickinessQuery`, `LifecycleQuery`, ...) and adds view configuration: editor filters, header, results table, last-computation footer, and embedding flags.
The source query defines _what_ to compute; the `InsightVizNode` defines _how_ it is presented and edited.

## Rendering

This is the node you actually pass to `<Query />` when rendering any insight:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'
import { NodeKind } from '@posthog/query-frontend/schema/schema-general'

;<Query
  query={{
    kind: NodeKind.InsightVizNode,
    full: true, // show with most visual options enabled, as in the insight scene
    source: {
      kind: NodeKind.TrendsQuery,
      series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
    },
  }}
  setQuery={(query) => {
    /* receive edited query back */
  }}
/>
```

View props on the node itself (`full`, `showHeader`, `showTable`, `showCorrelationTable`, `showLastComputation`, `showFilters`, `showResults`, `embedded`, `vizSpecificOptions`, ...) toggle individual surfaces; see `InsightVizNodeViewProps` in `../../schema/schema-general.ts`.

## Key files

- `InsightViz.tsx` — entry point. Builds `InsightLogicProps` and `DataNodeLogicProps` from the query and context, binds `insightLogic`, `insightDataLogic`, and `dataNodeLogic` via `BindLogic`, and renders `EditorFilters` next to `InsightVizDisplay`.
- `InsightVizDisplay.tsx` — the display column: header, the chart for the active insight kind (`TrendInsight`, `Funnel`, `RetentionContainer`, `Paths`), legend, detailed results table, and the funnel correlation section.
- `insightDataLogic.tsx` — owns the full query (`InsightVizNode`) for an insight: `setQuery`, loading via `dataNodeLogic`, export context, and draft/save handling.
- `insightVizDataLogic.ts` — the editing surface over the _source_ query. Exposes decomposed state (`querySource`, `series`, `interval`, `dateRange`, `breakdownFilter`, `compareFilter`, `display`, formulas, goal lines, ...) and update actions (`updateQuerySource`, `updateInsightFilter`, `updateBreakdownFilter`, `updateDateRange`, ...). The per-kind data logics (`trendsDataLogic`, `funnelDataLogic`, `retentionLogic`, `pathsDataLogic`) all connect to it.
- `sharedUtils.ts` — `keyForInsightLogicProps`, filter type guards.
- `utils.ts` — `getDefaultQuery`, `queryFromKind`, cached-result extraction, validation error parsing.

These kea logics are an internal implementation detail of the `<Query />` tag.
Consumers pass `query`/`setQuery` props and should not bind the logics directly (use `attachTo` if a scene logic needs to track them).

## Notable sub-components

- `EditorFilters.tsx` + `EditorFilters/` — the left-hand editing panel; one control per query feature (funnel steps, retention conditions, paths event types, lifecycle toggles, goal lines, sampling, PoE mode, ...), assembled per insight kind.
- `filters/` — shared filter widgets (action filter rows, breakdown, attribution, aggregation target).
- `views/InsightsTable/` — the detailed results table shown under trends charts (and as the `ActionsTable` display mode).
- `EmptyStates/` — empty, error, timeout, and validation-error states.
- `InsightDisplayConfig.tsx` — the toolbar above the chart (date range, interval, chart type, options).
- `ResultCustomizationsModal.tsx` — per-series color/visibility overrides.

Chart surfaces themselves live in `@posthog/visualizations` (`common/visualizations/`) and are used by the per-kind folders (`../TrendsQuery/`, `../FunnelsQuery/`, ...).
