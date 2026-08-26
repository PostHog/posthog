---
name: building-charts
description: >
  App-side guide for building or changing any chart, sparkline, or metric tile under
  `frontend/src/` or `products/*/frontend/` with `@posthog/quill-charts`. Use when adding a chart
  to a scene or product, changing an existing chart's axes, tooltip, legend, or thresholds,
  wiring drag-to-zoom or click drill-downs, deciding between a sparkline and a full chart, or
  testing and screenshotting chart UI. Covers the `lib/charts/hooks` seams (`useChartTheme`,
  `useChartConfig`, `useDateRangeZoom`), the product analytics reference implementations to copy
  from, integration gotchas (ISO labels, flex sizing, timezones, goal lines vs reference lines),
  and chart testing and story conventions. The component API itself lives in
  `packages/quill/packages/charts/AGENTS.md` — this skill is its app-side companion, not a
  replacement.
---

# Building charts

Every chart in the app renders through [`@posthog/quill-charts`](../../../packages/quill/packages/charts/AGENTS.md) —
canvas-rendered, themed from quill design tokens.
Read that AGENTS.md before writing chart code: it owns the chart-choice table and the full config, overlay, tooltip, and legend API.
This skill covers what it doesn't: the app-side seams, which existing chart to copy from, and the integration mistakes that recur.

Ground rules:

- **Never add Chart.js.** Nothing renders through it anymore; the leftover `frontend/src/lib/Chart.ts` / `lib/hooks/useChart.ts` shims are pending deletion. Do not import them or add any new charting dependency.
- **Chart changes ship unflagged.** Replace the old rendering outright in the same PR — no quill/legacy dispatcher component, no rollout flag. Cover the change with a story (visual review is the safety net) and tag the error boundary so the rollout is observable.
- **Chart data building is logic, not JSX.** Build series/labels/config in pure, unit-tested transform functions (or a kea selector), and keep the component a thin adapter. `trendsChartTransforms.ts` next to `TrendsLineChart.tsx` is the shape to copy.

## Sparkline or full chart?

It's a **full chart** (`TimeSeriesBarChart` / `TimeSeriesLineChart` / `BarChart`) if it needs any of:
a visible axis, drag-select (`onDateRangeZoom`), threshold lines, an externally controlled highlight (`HighlightedRange`),
incomplete-bucket striping (`stroke.partial` / per-bar `hatch`), or a standalone legend.

It's a **sparkline** only if it is compact, axis-less, non-interactive, and inline (a table cell, a card corner).
Multi-series alone does not promote it.
Do not force chart features through the sparkline wrapper — promote to a real chart instead, and budget more height (a real axis needs room; `h-24` sparklines typically become `h-32` charts).

- Inline sparklines in the main app: use the app wrapper `frontend/src/lib/components/Sparkline.tsx` (data normalization, app colors, loading skeleton), not quill's `Sparkline` directly.
- Headline number + trend + change pill: `MetricCard`.
- Exactly two snapshots (before/after) across several series: `SlopeChart` — see `/visualizing-change-over-time`.

## The app seams — wire all of them

Every app chart goes through `frontend/src/lib/charts/hooks.ts`.
The canonical shape:

```tsx
import { TimeSeriesLineChart } from '@posthog/quill-charts'
import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

const theme = useChartTheme()
const config = useChartConfig(
    () => ({
        xAxis: { timezone, interval },
        yAxis: { format: 'numeric' },
    }),
    [timezone, interval]
)

<div className="flex h-64 flex-col">
    <TimeSeriesLineChart
        series={series}
        labels={isoLabels}
        theme={theme}
        config={config}
        onError={handleChartError}
    />
</div>
```

- `useChartTheme()` — reads the design tokens and tracks light/dark switches. Never call `themeFromCssVars()` directly in the app; it doesn't react to theme changes.
- `useChartConfig(factory, deps)` — layers the app-wide chart defaults under your config. Note it shallow-merges: your `xAxis`/`yAxis` object replaces wholesale, only `tooltip` merges key by key. Skip it only for deliberately chromeless charts (e.g. an axis-less scatter) that opt out of all app chrome with their own config.
- `useDateRangeZoom(dates, onZoom)` — the drag-to-zoom seam, gated on the app-wide rollout flag. Use it when dragging is an extra affordance on top of a date filter the user can reach some other way. When the drag is the _only_ way to narrow the view beside the chart, wire the chart's `onDateRangeZoom` directly instead — gating it would remove an interaction users depend on (`frontend/src/scenes/hog-functions/invocations/InvocationsSparkline.tsx` is the reference).
- Error boundary: pass an `onError` that captures to PostHog with a stable `feature` name (see `makeChartErrorHandler` in `products/product_analytics/frontend/insights/trends/shared/chartErrorHandler.ts`). Filtering `$exception` on that property is how a chart change is watched after it ships.
- Value/date formatting helpers live in `frontend/src/lib/charts/utils/`.

## Copy from a reference implementation

Product analytics insights (`products/product_analytics/frontend/insights/`) are the source of what good app charts look like — trends, stickiness, retention, and funnels all live there.
Find the existing chart closest to what you're building and follow its structure:

| You need                                                                              | Copy from                                                                                                                 |
| ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| A full-featured time-series chart (legend, goal lines, annotations, click drill-down) | `insights/trends/TrendsLineChart/` — tested transforms, `useInsightsLegendConfig`, `goalLinesAdapter`, `AnnotationsLayer` |
| Stacked/grouped time-series bars                                                      | `insights/trends/TrendsBarChart/`                                                                                         |
| Part-of-whole                                                                         | `insights/trends/TrendsPieChart/`                                                                                         |
| A funnel                                                                              | `insights/funnels/`, or `frontend/src/scenes/experiments/charts/funnel/ExperimentFunnelChart.tsx`                         |
| A custom tooltip                                                                      | `insights/shared/InsightSeriesTooltip.tsx`, or experiments' `charts/funnel/FunnelTooltip.tsx`                             |
| A confidence-interval ribbon                                                          | `frontend/src/scenes/experiments/MetricsView/new/VariantTimeseriesChart.tsx` (`config.confidenceIntervals`)               |
| A compact volume chart with drag-select                                               | `frontend/src/scenes/hog-functions/invocations/InvocationsSparkline.tsx`                                                  |
| Threshold lines, anomaly points, dual y-axis                                          | `products/alerts/frontend/` chart components (`ReferenceLines`, `AnomalyPointsLayer`, `yAxis` array)                      |
| A scatter plot                                                                        | `products/ai_observability/frontend/clusters/ClusterScatterPlot.tsx`                                                      |

## Integration gotchas

- **Hand the chart raw ISO timestamps, not pre-formatted label strings.** `labels` must be unique — the x-scale keys positions off the strings, and display labels like "1–7 Jun" repeat across years, snapping points back to the first occurrence. Let `xAxis.timezone`/`interval` format ticks and the tooltip header. Guard the data builder with a test asserting `labels` are timestamps.
- **Give the chart a flex column parent.** The chart root is `flex-1`; dropped into a plain fixed-height `div` the canvas collapses to zero height. `<div className="flex h-64 flex-col">` is the fix.
- **Don't set `xAxis.tickLabelRotation`.** Quill drops overlapping labels itself; no app chart slants its date axis. Slanted labels were a Chart.js workaround — don't port them.
- **A threshold the user must always see goes in `config.goalLines`, not a `ReferenceLine` child.** A goal line stretches the value axis so a limit above the tallest bar stays on-plot; a `ReferenceLine` renders off-plot (i.e. not at all) in that case. Use `ReferenceLine` for markers within the data's range.
- **Carry timezone semantics onto the axis and tooltip, not just the data.** If buckets are cut in the project's timezone, pass that zone to the tick formatter and the tooltip's `labelFormatter` too — formatting in the viewer's zone shifts a project-local day to the day before.
- **Restyle tooltips when you touch them.** Prefer `config.tooltip` fields (formatters, totals, sorting) over a render prop. A genuinely custom tooltip builds its panel from `TooltipSurface`/`TooltipSwatch`/`TooltipFooter` with surface-relative muted text (`opacity-60`, `border-current/25`) — never a hand-rolled panel of app tokens (`bg-surface-primary`), which ignores the chart theme.

## Testing and stories

- **Unit-test the pure transforms; story-test the rendering.** Don't assert quill config plumbing through a rendered canvas in jsdom (series counts, tick strings) — that tests the charts package, not your code. A chart regression is visual; a story with a snapshot catches it.
- **Render the real product component in the story, not a hand-assembled chart.** A story that builds its own `TimeSeriesLineChart` bypasses `useChartConfig()` and silently diverges from what ships.
- Interaction tests use `@posthog/quill-charts/testing` (`getHogChart`, `hoverUntilTooltip`, `createDefaultTooltipAccessor`) — the package AGENTS.md documents them. If a component being migrated has a `jest.mock('lib/components/Sparkline')`, delete the mock and assert against the real canvas.
- Tests inside `packages/quill/packages/charts/` misroute under `hogli test` (package-local jest without a TS transform) — run them with `cd frontend && pnpm exec jest --config jest.config.ts <path>`.
- A new story adds two snapshot identifiers (light + dark). Visual review reporting them as "new" and going red until accepted is the normal flow, and a bot then commits updated baselines onto your branch — fetch before your next push.
