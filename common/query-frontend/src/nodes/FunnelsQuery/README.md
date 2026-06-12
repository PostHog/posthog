# FunnelsQuery

`FunnelsQuery` measures conversion through an ordered list of steps.
Each entry in `series` is a step (event, action, or data warehouse entity); `funnelsFilter` controls the funnel semantics (conversion window, step order, exclusions, attribution) and the visualization (`funnelVizType`, `layout`); `breakdownFilter` splits conversion by a property, cohort, or event.

## Rendering

`FunnelsQuery` is an insight _source_ — wrap it in an `InsightVizNode` and pass that to `<Query />`:

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'
import { NodeKind } from '@posthog/query-frontend/schema/schema-general'

;<Query
  query={{
    kind: NodeKind.InsightVizNode,
    source: {
      kind: NodeKind.FunnelsQuery,
      dateRange: { date_from: '-7d' },
      series: [
        { kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' },
        { kind: NodeKind.EventsNode, event: 'signed_up', name: 'signed_up' },
      ],
      funnelsFilter: { funnelVizType: 'steps' },
    },
  }}
/>
```

See `InsightFunnelsQuery` in `../../examples.ts` for an example with a breakdown.

## Visualizations

`Funnel.tsx` switches on `funnelsFilter.funnelVizType`:

- `steps` (default) → `FunnelBarVertical/` or `FunnelBarHorizontal/`, depending on `funnelsFilter.layout`
- `trends` → `FunnelLineGraph.tsx` (conversion rate over time, drawn with `LineGraph` from `@posthog/visualizations`)
- `time_to_convert` → `FunnelHistogram.tsx` (distribution of conversion times, `Histogram` from `@posthog/visualizations`)
- `flow` → `FunnelFlowGraph/` (node/edge flow diagram)

## Key files

- `Funnel.tsx` — top-level component, picks the visualization.
- `funnelDataLogic.ts` — kea logic keyed by `InsightLogicProps`. Connects to `insightVizDataLogic` and derives `steps` with conversion metrics, flattened breakdown rows, time-to-convert bins, conversion window, step reference, incomplete-conversion-window detection, result customizations (colors), and visibility of hidden breakdown legends.
- `funnelUtils.tsx` — pure helpers: `stepsWithConversionMetrics`, `aggregateBreakdownResult`, `flattenedStepsByBreakdown`, conversion window math.
- `funnelPersonsModalLogic.ts` — opens the persons modal for a step, drop-off, or trends entrance period (via `FunnelsActorsQuery`).
- `funnelCorrelationLogic.ts`, `funnelPropertyCorrelationLogic.ts`, `funnelCorrelationDetailsLogic.ts`, `funnelCorrelationUsageLogic.ts` — event and property correlation analysis shown under the funnel.
- `funnelTooltipLogic.ts` — hover tooltip state for funnel charts.

The kea logics here are an internal implementation detail of the `<Query />` tag.
Consumers pass `query`/`setQuery` props to `<Query />` and should not bind these logics directly.

## Notable sub-components

- `FunnelBarVertical/` — `StepBars`, `StepBarLabels`, `StepLegend`.
- `FunnelBarHorizontal/` — `Bar`, `DuplicateStepIndicator`.
- `views/` — `FunnelStepsTable`, `FunnelCorrelationTable`, `FunnelPropertyCorrelationTable`, `CorrelationMatrix`, plus editor pickers (`FunnelVizType`, `FunnelDisplayLayoutPicker`, `FunnelConversionWindowFilter`, `FunnelBinsPicker`, `FunnelStepOrderPicker`, `FunnelStepsPicker`).
- `FunnelCanvasLabel.tsx`, `FunnelTooltip.tsx`, `ValueInspectorButton.tsx`, `FunnelStepMore.tsx` — chrome around the charts.

Shared chart surfaces (`LineGraph`, `Histogram`, etc.) live in `@posthog/visualizations` (`common/visualizations/`).
