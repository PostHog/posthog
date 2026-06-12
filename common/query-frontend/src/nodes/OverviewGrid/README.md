# OverviewGrid

Presentational grid of metric tiles — value, label, and change versus the previous period.
This is not a query node kind: it renders no query and holds no kea logic.
It is the shared display layer behind `WebOverview` (the `WebOverviewQuery` renderer) and the marketing, revenue, and endpoints overview nodes, which map their query responses into `OverviewItem[]` and pass them here.

## Usage

```tsx
import { OverviewGrid } from '@posthog/query-frontend/nodes/OverviewGrid/OverviewGrid'

;<OverviewGrid
  items={[
    { key: 'visitors', value: 1234, previous: 1000, changeFromPreviousPct: 23.4, kind: 'unit' },
    {
      key: 'bounce rate',
      value: 0.45,
      previous: 0.5,
      changeFromPreviousPct: -10,
      kind: 'percentage',
      isIncreaseBad: true,
    },
  ]}
  loading={false}
  numSkeletons={5}
  labelFromKey={(key) => key.toUpperCase()}
/>
```

To render a query instead, use `<Query />` with a query whose node maps into this grid, e.g. a `WebOverviewQuery` (see `../WebOverview`).

## Key files

- `OverviewGrid.tsx` — the grid:
  - `OverviewItem` — `key`, `value`, `previous`, `changeFromPreviousPct`, `kind` (`unit` | `duration_s` | `percentage` | `currency`), `isIncreaseBad`, optional `warning`/`warningLink`, `caption`, `onClick`, `selected`
  - each cell shows the formatted value, a trend icon colored by whether an increase is good or bad, and a tooltip with the precise change
  - skeleton cells while `loading`, a `compact` mode, and pre-aggregation badges (`usedPreAggregatedTables`, `usedLazyPrecompute`, `onDisablePrecompute`)
  - `SamplingNotice` — banner when results are sampled (`samplingRate`)
  - `formatItem(value, kind, options)` — exported formatting helper (percentage, duration, currency, large-number)
- `OverviewMetricCardGrid.tsx` — alternative card-style layout (`OverviewMetricCardItem`), used by `WebOverview` behind the `web-analytics-metric-cards` feature flag
- `OverviewMetricCardGrid.stories.tsx` — storybook stories

Cells with `onClick` render as buttons (keyboard accessible) and can show a `selected` ring — used for click-to-filter overview tiles.
