---
name: visualizing-change-over-time
description: >
  Helps PostHog engineers and agents pick the right chart when a request is about
  visualizing change over time, before/after comparisons, or period-over-period
  movement while building UI with @posthog/quill-charts (dashboards, reports, the
  mcp_analytics frontend, custom visualizations). Use when a user asks how something
  "changed", "moved", "grew", "dropped", "improved", or "regressed" between two
  points or periods, or mentions "before/after", "period over period", "week over
  week", "delta", "slope graph", "slopegraph", or comparing many series across two
  snapshots. Surfaces both the `SlopeChart` quill component and the native
  `ChartDisplayType.SlopeGraph` insight display as options.
---

# Visualizing change over time

When a request is about **how something changed**, the default reach is a line/area
trend — and that is usually right for a continuous series with many x points. But for
some change-over-time shapes a different chart reads far better. This skill is the
menu to offer, including the **slope graph**, when building visualizations with
[`@posthog/quill-charts`](../../../packages/quill/packages/charts/AGENTS.md).

Present the fitting option(s) and let the user choose — none of these is mandatory.

## Pick by the shape of the change

| The change is…                                                            | Reach for                                                    | Why                                                                                                                                              |
| ------------------------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| A continuous series over many time points (a trend)                       | `TimeSeriesLineChart` / `LineChart` (area fill for emphasis) | The standard trend; the slope between every pair of points is visible.                                                                           |
| **Two points only** (before → after) across **several series/categories** | **`SlopeChart`**                                             | One line per entity from a left "before" to a right "after" — direction and magnitude of each entity's change, and rank flips, read at a glance. |
| Magnitude comparison at points in time (not the path between them)        | `BarChart` / `TimeSeriesBarChart`                            | Bars compare discrete values; group/stack for sub-series.                                                                                        |
| A single headline number plus its change vs a prior period                | `MetricCard`                                                 | Big number + sparkline + change pill.                                                                                                            |

If the user is comparing exactly **two snapshots** (this week vs last, control vs
treatment, Q1 vs Q2) and especially when there are **many categories** whose
_relative_ movement matters, offer the slope graph as the cleaner alternative to a
grouped bar or a 2-point line chart.

## Using the SlopeChart

```tsx
import { SlopeChart } from '@posthog/quill-charts'
import type { Series } from '@posthog/quill-charts'
import type { SlopeSeriesMeta } from '@posthog/quill-charts'

// One series per entity; `data` is exactly [start, end].
const series: Series<SlopeSeriesMeta>[] = [
    { key: 'us', label: 'US', data: [120, 185] },
    { key: 'eu', label: 'EU', data: [200, 150] },
]

<SlopeChart
    series={series}
    labels={['Before', 'After']}
    theme={theme}
    config={{
        showSeriesLabels: true, // name beside each end point; steepest line always keeps its label
        legend: { show: true }, // each row shows the color, label, and the formatted change
        deltaFormatter: (d) => `${d >= 0 ? '+' : ''}${d}`,
    }}
/>
```

Key options (full list in the charts
[AGENTS.md](../../../packages/quill/packages/charts/AGENTS.md) "Composition" section):

- `showStartLabels` / `showEndLabels` — chart-level defaults for the value labels;
  override per series with `meta.showStartLabel` / `meta.showEndLabel`.
- `showSeriesLabels` — the name labels; on collision the series with the **largest
  change** (`|end − start|`) always keeps its label.
- `legend: { show, position }` — rows carry the per-series change (`deltaFormatter`).
- The value axis is hidden by default — the start/end labels are the readout.

The theme comes from `useChartTheme()`; give the wrapper a real height. See the
charts AGENTS.md for theme wiring and sizing.

## Scope note

There are **two** ways to render a slope graph; which you reach for depends on the surface:

- **`SlopeChart`** — the `@posthog/quill-charts` component. Use it when building UI
  directly: dashboards, reports, the `mcp_analytics` frontend, custom visualizations.
  It backs the **Slope** view toggle on Max's inline trends result card
  (`services/mcp/src/ui-apps/components/TrendsVisualizer.tsx`).
- **`ChartDisplayType.SlopeGraph`** — a first-class insight display (value
  `'SlopeGraph'` in `frontend/src/types.ts`), rendered by the backend
  `SlopeGraphTrendsQueryRunner`
  (`posthog/hogql_queries/insights/trends/slope_graph_trends_query_runner.py`). It
  takes a `TrendsQuery` and keeps the **first and last bucket** of the date range as
  the two slope points (the last segment is dashed when it's the current,
  still-accumulating period). Set it via `trendsFilter.display: "SlopeGraph"`
  (trends-only).
  - In the **product insight editor**, the picker entry is gated behind
    `FEATURE_FLAGS.SLOPE_GRAPH_INSIGHT` (`slope-graph-insight`).
  - Via the **API / `posthog:insight-create` MCP tool** it works without the flag —
    pass a `TrendsQuery` with `trendsFilter.display: "SlopeGraph"`. To frame a clean
    before → after, choose the date range and `interval` so the first bucket is your
    baseline and the last is "now" (e.g. monthly buckets starting from the baseline
    month).
