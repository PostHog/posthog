---
name: working-with-charts
description: How to add or change a chart in the PostHog app with `@posthog/quill-charts`, the canvas charting library behind trends, funnels, retention, SQL insights, and product dashboards. Use ALWAYS before creating or editing a chart component, changing a chart's series, config, theme, legend, tooltip, or overlays, adding a chart child (reference line, value labels, annotations, markers), wiring chart clicks or drag-to-zoom, or touching `packages/quill/packages/charts/`. Covers which chart type fits the data, the app-side defaults (`useChartTheme`, `useChartConfig`, `INSIGHT_TOOLTIP_CONFIG`, legend hooks), the tooltip ladder from `config.tooltip` through `DefaultTooltip` and `InsightSeriesTooltip` to a custom surface, the overlays that exist, and how to write a new one. Trigger terms - quill-charts, hog-charts, LineChart, BarChart, TimeSeriesLineChart, PieChart, FunnelChart, ScatterChart, Sparkline, MetricCard, tooltip, legend, ReferenceLine, ValueLabels, useChartLayout, chart overlay, ChartDisplayType.
---

# Working with charts

`@posthog/quill-charts` draws series on a canvas, scales them with D3, and renders everything a user reads (axis labels, tooltip, legend, reference lines, value labels) as React DOM positioned from the scales.
The library knows nothing about PostHog.
The app wraps it with a small set of adapters, and every chart in the app follows the same shape.

## Read first

1. [packages/quill/packages/charts/AGENTS.md](../../../packages/quill/packages/charts/AGENTS.md), the library's map: the chart table, the gotchas, and an index of topic docs under `src/docs/` (axes, bars, tooltips, legend, overlays, interactions, chart types). Prop semantics are JSDoc on the types. This skill does not repeat any of it.
2. The adapter closest to what you are building. `TrendsLineChart` and `TrendsBarChart` under `products/product_analytics/frontend/insights/trends/` exercise nearly every feature; [chart-types.md](./references/chart-types.md) names a precedent for each chart type.
3. The reference in this skill for the part you are touching: [chart-types.md](./references/chart-types.md), [tooltips.md](./references/tooltips.md), [overlays.md](./references/overlays.md), [testing-and-stories.md](./references/testing-and-stories.md).

## One home per fact

A fact that is true of the library in any host (a prop, a context field, an overlay or tooltip rule) lives once, in the library's `src/docs/`, and this skill links to it.
This skill and its references hold only what is true of the PostHog app: the `lib/charts` hooks, the insight tooltip and legend wiring, the precedents, and where files go.
If you are writing a library fact here, move it to the topic doc and link.

## Where code goes

| Zone               | Path                                                                                                                                                                                        | Rules                                                                                                                                                                                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Library            | `packages/quill/packages/charts/src/`                                                                                                                                                       | No kea, no PostHog imports, no `lib/`, `scenes/`, or `~/` paths. Generic props only. Every change writes the JSDoc, adds a story, and updates the topic doc under `src/docs/`. Export new public symbols from `src/index.ts`.                            |
| Pure transform     | `*Transforms.ts` or `*Adapter.ts` next to the adapter                                                                                                                                       | Turns product results into `Series[]`, `labels`, and config. No kea, no React. Inject `getColor`, `getLabel`, `buildMeta` as callbacks. Keep it free of `lib/`, `scenes/`, and `~/` imports when MCP UI apps reuse it. Always has a sibling `*.test.ts`. |
| Adapter            | `products/<product>/frontend/...` or `frontend/src/scenes/...`                                                                                                                              | The React component. Reads kea, builds series and config through the transform, passes callbacks and overlay children. One component per chart type.                                                                                                     |
| Shared app helpers | `frontend/src/lib/charts/`, `frontend/src/lib/components/AnnotationsOverlay/`, `frontend/src/lib/components/ChartLegendSeriesMenu/`, `products/product_analytics/frontend/insights/shared/` | Reuse before writing a sibling.                                                                                                                                                                                                                          |

A change that puts kea or a PostHog type in the library, or inlines a transform into the component, is wrong regardless of how small it is.

## The adapter shape

Every app chart is this component, with parts dropped when unused:

```tsx
export function MyChart({ results }: Props): JSX.Element {
  const theme = useChartTheme() // from 'lib/charts/hooks', not from the library
  const { timezone } = useValues(teamLogic)

  const { series, labels } = useMemo(() => buildMySeries(results, { getColor }), [results, getColor])

  const config = useChartConfig(
    () => ({
      xAxis: { timezone, interval: 'day', allDays: labels },
      yAxis: { format: 'numeric', showGrid: true },
      tooltip: INSIGHT_TOOLTIP_CONFIG,
      legend: legendConfig,
    }),
    [timezone, labels, legendConfig]
  )

  if (!series.length) {
    return <InsightEmptyState />
  }

  return (
    <TimeSeriesLineChart<MyMeta>
      series={series}
      labels={labels}
      theme={theme}
      config={config}
      tooltip={renderTooltip}
      onPointClick={onPointClick}
      onDateRangeZoom={onDateRangeZoom}
      dataAttr="my-chart"
      onError={handleChartError}
    >
      <AnnotationsLayer insightNumericId={insight.id} dates={labels} />
    </TimeSeriesLineChart>
  )
}
```

### Theme

`useChartTheme` from `frontend/src/lib/charts/hooks.ts`.
It builds the theme from the app palette and graph tokens, and re-reads on the light/dark flip.
The library's own `useChartTheme` reads quill tokens and misses the app's theme attribute, so it belongs only in quill-native surfaces (the desktop app, MCP UI apps).
Pass a memoized `overrides` object if you override anything.
Resolve the theme once per scene and pass it down when a grid renders many charts.

### Series

- `key` is a stable id from the data (`String(result.id)`), so click handlers and the legend can resolve back to the source. Never an array index.
- `labels` are unique strings. On time-series charts pass ISO dates and let `xAxis.timezone` and `interval` format them. Display labels repeat across years and collapse points onto each other.
- `data.length === labels.length`. Use `NaN` for a missing value, not `null`.
- Omit `color` to take the palette by index; set it only when the product owns the color (insight result customizations, lifecycle statuses, spike bars). Canvas cannot paint `var(--x)` or `oklch()`; resolve tokens with `resolveVariableColor` or `getColorVar` first.
- `meta` carries everything a tooltip or click handler needs. Type it (`Series<MyMeta>`) and read it from `entry.series.meta` or `clickData.series.meta`, never from array position. Insight charts use `TrendsSeriesMeta` built by `buildTrendsSeriesMeta`.
- Hidden series stay in the array and are excluded through `config.legend.hiddenKeys`, so the legend can restore them. Drop them only where a hidden row would leave an empty band (aggregated bar value).
- `stroke: { partial: { fromIndex } }` dashes the in-progress tail. Compute the index once and share it with anything else that needs the boundary (trend line `fitUpTo`).
- `overlay: true` on trend lines and moving averages. Confidence bands are not overlays.
- `yAxisId` puts a series on a second axis. Trends assigns them per magnitude cluster with `computeMagnitudeAxisIds`.
- Memoize the array. A new `Series[]` every render recomputes the scales and repaints the canvas.

### Config

Build it with `useChartConfig(factory, deps)` from `lib/charts/hooks`.
It layers `DEFAULT_CHART_CONFIG` (monotone curve, grid, axis lines, tick marks, crosshair, rounded bars, cursor-anchored tooltip) under whatever the factory returns, and merges `tooltip` key by key.
Omit keys you do not set rather than passing `undefined`, and opt out field by field (`showGrid: false`) rather than rebuilding the chrome.

The keys most charts set:

- `xAxis: { timezone, interval, allDays, label }` on time-series wrappers. `tickLabelRotation: -45` for long categorical labels.
- `yAxis: { format, prefix, suffix, decimalPlaces, currency, scale, showGrid, startAtZero, min, max, label }`. Insight charts derive this from the trends filter with `buildTrendsYAxisConfig` in `products/product_analytics/frontend/insights/trends/shared/trendsAxisFormat.ts`, which also knows when a percent stack or log axis vetoes the range. Percent layouts want `format: 'percentage_scaled'`. An array of `yAxis` entries with `id` and `position` gives each axis its own format.
- `tooltip`: `INSIGHT_TOOLTIP_CONFIG` (`{ pinnable: true, placement: 'cursor' }`) for anything with a drill-down; `{ enabled: false }` for sparklines. See [tooltips.md](./references/tooltips.md).
- `legend`: see below.
- `goalLines` on time-series wrappers, mapped from the schema with `schemaGoalLinesToConfigs`.
- `valueLabels: { formatter }` on time-series wrappers, `<ValueLabels>` child on base charts. In percent layouts the formatter receives a 0..1 fraction.
- `barLayout`, `divergingStack` (negative values stack below zero), `maxCategoryLabelWidth: MAX_CATEGORY_LABEL_WIDTH` for breakdown labels that can be URLs.
- `margins` only for sparklines that need the plot flush with the edges or an overlay that needs headroom. Pass a module-level constant.

Bar and combo charts ignore `yAxis.min` and `max` by design; pin `valueDomain` there instead.

### Legend

- Insight charts whose visibility persists into the query: `useInsightsLegendConfig({ insightProps, inSharedMode })`. It wires `hiddenKeys`, `onToggleSeries`, `onSetHiddenSeries`, `visibilityGroupKey` (compare-period rows share one stored bit), and the row menu.
- Charts with nowhere to persist (SQL insights, lifecycle, funnels, product dashboards): `buildBaseLegendConfig` plus `useChartLegendSeriesMenu({ surface, seriesCount })` as `renderItem`, or a plain `{ show, position, interactive }`. The chart owns the toggled state.
- `show` is the product's toggle, and `interactive` is false in shared and embedded read-only views.
- A sole series needs no legend.

Legend rows list the user's series only; derived trend lines and bands follow their parent.

### Tooltip

Prefer the built-in tooltip.
Configure behavior and formatting through `config.tooltip`; wrap `DefaultTooltip` in a render prop only for `labelRenderer`, `showHeader`, `hideZeroRows`, `onRowClick`, or `footer`; use `InsightSeriesTooltip` for anything that shows insight results; compose `TooltipSurface`, `TooltipSwatch`, and `TooltipFooter` only when the panel is not a list of series rows.
The full ladder, with the context fields a tooltip should read, is in [tooltips.md](./references/tooltips.md).

### Overlays

Children of the chart.
Library overlays: `ReferenceLine(s)`, `ValueLabels`, `AxisTitles`, `TrendLineOverlay`, `HighlightedRange`, `AnomalyPointsLayer`.
App overlays to reuse: `AnnotationsLayer` (any insight chart with dates), `TrendsAlertOverlays` (alert thresholds and anomalies on trends).
Anything that reads product state stays in the product.
Writing a new one, and the hooks it reads, are in [overlays.md](./references/overlays.md).

### Interactions

- `onPointClick(data: PointClickData<Meta>)` gives `series`, `dataIndex`, `label`, `value`, `crossSeriesData`, and `inTrackArea` on grouped bars. Insight charts route it through `handleTrendsChartClick`, which resolves the result by `series.key`, prefers `context.onDataPointClick`, and otherwise opens the persons modal with `datasetToActorsQuery`. Copy that shape rather than opening the modal inline.
- Drag-to-zoom: `onDateRangeZoom={useDateRangeZoom(dates, context?.onDateRangeZoom)}`. The hook maps dragged indices to dates, orders them, and returns `undefined` unless the rollout flag is on and the host passed a handler, so every surface is gated in one place. The host widens the end bucket; the chart emits bucket starts.
- `onAreaSelect` on `ScatterChart` and `onBrush` on `Heatmap` are the 2D equivalents.
- `FunnelChart` uses `onStepClick` with `converted`; `PieChart` uses `onSliceClick`; `BoxPlot` uses `onBoxClick`.
- Wrap every callback in `useCallback`. Unstable handlers re-register the chart's interaction layer.

### Chrome around the chart

- The wrapper needs a real height. A chart in a zero-height flex child renders nothing; give the parent `h-64`, or `flex flex-col` with the chart as `flex-1` inside a sized column. The top-or-bottom legend cap needs an explicit `height`, not a flex-derived one.
- Render the empty state instead of the chart when there is no data (`InsightEmptyState` for insights, `hasTrendsChartData` as the gate).
- `onError={makeChartErrorHandler('my-chart')}` (or a local `posthog.captureException` with a `feature` tag) so a tooltip or overlay throw reports instead of unmounting the scene.
- `dataAttr` names the wrapper for tests and stories (`trend-line-graph`, `trend-bar-graph`).
- Compare-to-previous series render dimmed: `comparisonOf` in the time-series line config, `dimHexColor` on bar and stickiness series.

## Adding a chart to insights

1. Add the `ChartDisplayType` case to `renderViz` in `frontend/src/scenes/trends/Trends.tsx` (or the funnel, retention, or paths equivalent).
2. Create `products/product_analytics/frontend/insights/<family>/<Name>Chart/` with `<Name>Chart.tsx`, `<name>ChartTransforms.ts`, tests for both, and `<Name>Chart.stories.tsx`.
3. Reuse `useInsightsLegendConfig`, `InsightSeriesTooltip`, `handleTrendsChartClick`, `TrendsAlertOverlays`, `AnnotationsLayer`, `buildTrendsYAxisConfig`, and `goalLinesAdapter` before writing anything new.
4. If the display is exposed to MCP UI apps, keep the transform free of `lib/`, `scenes/`, and `~/` imports; `products/product_analytics/frontend/insights/trends/shared/trendsChartDisplayOptions.ts` shows the structural types that firewall works through.
5. Update the editor's display options and any docs under `docs/` that list display types.

## If the change reaches into the library

- Read `packages/quill/packages/charts/src/docs/CONTRIBUTING.md` for the layers (chart types, core, canvas renderer, overlays) and where new code goes.
- Geometry goes in `core/scales.ts` or `core/bar-layout.ts` and is tested there. Drawing goes in `core/canvas-renderer.ts` as stateless functions. Chart-private state goes through `scales._private`, not `useRef`.
- Keep the hover path cheap: no allocations, no static repaint, no layout-context updates on mousemove. The target is a thousand series by a hundred thousand points.
- Add a `data-attr` and an accessor method in `src/testing/accessor.ts` for anything a test will need to read.
- Write the JSDoc on the prop, add a story next to the component, and update the matching topic doc under `src/docs/` in the same PR. Touch the library `AGENTS.md` only when the change alters which chart to pick or adds a gotcha. A lint-staged warning fires when quill sources change without a doc update.
- The app's Vite build imports the package from its dist. Rebuild `@posthog/quill-charts` locally to see a library change in the app; do not restart the frontend for it.

## Tests and stories

Pure transform tests next to the transform, adapter tests rendering the real scene through `renderInsight` or `getHogChart`, stories with a sized stage and a pinned `mockDate`.
Never mock the library, query the canvas, or snapshot pixels.
Details in [testing-and-stories.md](./references/testing-and-stories.md).

## Checklist before opening the PR

- The chart type matches the data shape and a precedent in [chart-types.md](./references/chart-types.md).
- Theme from `lib/charts/hooks`, config through `useChartConfig`, series and callbacks memoized.
- Labels unique, ISO dates on time-series charts, `key` a stable id, `meta` typed.
- Hidden series handled through the legend, not by filtering.
- Tooltip on the lowest rung of the ladder that meets the requirement; `pinnable` set when rows are clickable; `onUnpin` called before opening a modal.
- Overlays positioned from the scales, hidden outside the plot, marked `data-hog-charts-interactive-overlay` when interactive.
- Wrapper has a real height; empty state, `onError`, and `dataAttr` set.
- Transform test, adapter test, and story added; JSDoc and the topic doc under `src/docs/` updated if the library changed.
- Visual check at a narrow width (the scene can be about 520px wide with the sidebar and side panel open).
