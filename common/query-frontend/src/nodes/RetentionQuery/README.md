# RetentionQuery

`RetentionQuery` measures how many users come back over time.
Users who perform the `targetEntity` event in a period form a cohort, and each cohort is tracked for how many members perform the `returningEntity` event in subsequent periods.
The required `retentionFilter` configures the entities, `period` (`Day`/`Week`/...), `totalIntervals`, retention type and reference, optional value aggregation (`aggregationType`/`aggregationProperty`), and display options; an optional `breakdownFilter` splits cohorts by a property.

## Rendering

`RetentionQuery` is an insight _source_ — wrap it in an `InsightVizNode` and pass that to `<Query />`:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'
import { NodeKind } from '@posthog/query-frontend/schema/schema-general'

;<Query
  query={{
    kind: NodeKind.InsightVizNode,
    source: {
      kind: NodeKind.RetentionQuery,
      retentionFilter: {
        targetEntity: { type: 'events', id: '$pageview', name: '$pageview' },
        returningEntity: { type: 'events', id: '$pageview', name: '$pageview' },
      },
    },
  }}
/>
```

See `InsightRetentionQuery` in `../../examples.ts`.
`InsightVizNode.vizSpecificOptions[InsightType.RETENTION]` can hide the line graph or size column and switch to a small layout (used by embedded surfaces).

## Key files

- `RetentionContainer.tsx` — top-level component; composes the graph, the cohort table, and the drill-down modal, respecting `retentionFilter.dashboardDisplay` and `vizSpecificOptions`.
- `retentionLogic.ts` — kea logic keyed by `InsightLogicProps`. Connects to `insightVizDataLogic` and derives processed retention results (percentages per cohort interval), mean retention rows (`retentionMeans`), breakdown handling, selected breakdown value, and custom bracket editing state.
- `retentionTableLogic.ts` — row/column shaping for the table view.
- `retentionGraphLogic.ts` — datasets for the line/bar graph view.
- `retentionModalLogic.ts` and `retentionPeopleLogic.ts` — open a cell's cohort in a modal and page through the actors behind it.

The kea logics here are an internal implementation detail of the `<Query />` tag.
Consumers pass `query`/`setQuery` props to `<Query />` and should not bind these logics directly.

## Notable sub-components

- `RetentionTable.tsx` — the classic retention grid with color-graded cells; clicking a cell opens `RetentionModal.tsx`.
- `RetentionGraph.tsx` — retention curves per cohort, drawn with `LineGraph` from `@posthog/visualizations` (`common/visualizations/`); `retentionFilter.display` switches between line and bar.
- `RetentionModal.tsx` — actor drill-down for a single cohort/interval cell.
- `RetentionDatePicker.tsx`, `RetentionBreakdownFilter.tsx` — editor controls (used from `../InsightViz/EditorFilters/`).
- `queries.ts`, `utils.ts`, `constants.ts`, `types.ts` — actor query builders and shared helpers (`ProcessedRetentionPayload`).
