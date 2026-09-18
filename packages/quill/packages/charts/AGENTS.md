# Charts — Agent Reference

Quick-reference for agents using `@posthog/quill-charts`. Canvas-rendered charts, D3 scales, React DOM overlays, themed via quill design tokens. Ships no CSS — colors come from CSS variables at runtime.

This file is the map. Prop-level semantics live in the JSDoc on the config and props types (`src/core/types.ts`, `src/utils/use-axis-formatters.ts`, each chart's `*Props`), and behavior that spans several fields lives in [`src/docs/`](./src/docs/). Read the type, then the topic doc, in that order.

## Choosing a chart

| Chart                  | Use when                                                                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `LineChart`            | Categorical x-axis trends; area fills, fill-between (confidence ribbons)                                                                    |
| `TimeSeriesLineChart`  | Time-indexed labels (ISO strings) with timezone/interval-aware x-axis; goal lines, trend lines, moving averages, confidence bands as config |
| `BarChart`             | Categorical comparisons — `barLayout: 'stacked' \| 'grouped' \| 'percent'`, `axisOrientation: 'horizontal'` for horizontal bars             |
| `TimeSeriesBarChart`   | Same x-axis handling as the time-series line chart, bar rendering, per-series `yAxisId` axes                                                |
| `ComboChart`           | Mixed bar/line/area series on one band x-axis — set `Series.type`; vertical only                                                            |
| `TimeSeriesComboChart` | `ComboChart` plus the time-series chrome (date x-axis, goal lines, legend, value labels)                                                    |
| `FunnelChart`          | Funnel steps as grouped bars over a hatched drop-off track — one band per step, one bar per variant, valued as percent of first step        |
| `PieChart`             | Part of whole, one value per series; `innerRadiusRatio` for a donut                                                                         |
| `ScatterChart`         | Two continuous numeric axes — one marker per `{ x, y }` point; takes `points`, not `labels`                                                 |
| `BoxPlot`              | Distribution summaries — `{ min, p25, median, mean, p75, max }` per label                                                                   |
| `Heatmap`              | 2D density grid (latency over time) — `xLabels` × `yLabels`, `cells[row][col]`                                                              |
| `SlopeChart`           | Change between two points — one line per series, `data: [start, end]`                                                                       |
| `Sparkline`            | Tiny inline trend, no axes — gradient line or stacked bars; tooltip off by default                                                          |
| `MetricCard`           | Headline number + sparkline + change pill (dashboard stat tiles)                                                                            |

Behavior notes per chart: [docs/chart-types.md](./src/docs/chart-types.md).

## Theme wiring

```tsx
import { useChartTheme } from '@posthog/quill-charts'

const theme = useChartTheme() // reads CSS vars, tracks light/dark switches
<LineChart series={series} labels={labels} theme={theme} />
```

- Series colors come from `--data-color-1..15`; chrome from `--color-graph-axis-label` / `--color-graph-axis-line` / `--color-graph-crosshair`. `themeFromCssVars()` is the one-shot version; `DEFAULT_CHART_COLORS` is the no-DOM fallback.
- Omit `color` on a series to get palette assignment by index (preferred). An explicit `color` must be a concrete color (hex, rgb): line, area, and bar series hand it to the canvas unresolved, so resolve `var(--...)` in the host first. Only `Heatmap` and `ScatterChart` resolve `var()` themselves.
- The theme helpers carry the default chrome (faint dashed grid, stronger axis line, dashed crosshair), and `DEFAULT_CHART_CONFIG` carries the matching switches. Consumers opt out field by field (`showGrid: false`). Details: [docs/axes.md](./src/docs/axes.md).
- `theme.skipDraw` mounts the canvas without painting, for deterministic visual snapshots.

## Series shape

```tsx
const series: Series[] = [
  { key: 'visits', label: 'Visits', data: [20, 35, 28] }, // data.length === labels.length
  { key: 'goal', label: 'Goal', data: [30, 30, 30], overlay: true }, // excluded from stacking and the baseline
]
```

- `key`, `label`, `data` are required. `key` is the React key and the stacking identity.
- `labels` must be unique. The x-scale keys positions off the strings; a duplicate collapses onto the first occurrence and draws the series backwards. On time-series charts pass ISO dates and format ticks via `xAxis.timezone` / `interval`.
- `meta` carries arbitrary data into tooltips and click handlers; narrow it with `Series<MyMeta>`.
- `visibility.{excluded,tooltip,total,valueLabel}` controls where a series appears. `overlay: true` marks a derived series (trend line, moving average). Line-only: `points`, `stroke.pattern`, `stroke.partial`, `fill`. Bar-only: `bars[]`, `trackData`. Full field docs on `Series` in `src/core/types.ts`.

## Sizing

Charts fill their container and need a parent with real dimensions — a zero-height flex child renders nothing. Give the wrapper an explicit height. `Sparkline` alone takes `height` / `width` props.

## Composition

```tsx
<TimeSeriesLineChart
  series={series}
  labels={isoLabels}
  theme={theme}
  config={{
    xAxis: { timezone: 'UTC', interval: 'day' },
    yAxis: { format: 'currency', currency: 'USD' },
    tooltip: { pinnable: true },
    legend: { show: true, position: 'right' },
  }}
>
  <ReferenceLine value={100} orientation="horizontal" variant="goal" label="Target" />
  <ValueLabels mode="stack-total" offset={8} />
</TimeSeriesLineChart>
```

- Overlays (`ReferenceLine`/`ReferenceLines`, `ValueLabels`, `AxisTitles`, `TrendLineOverlay`, `HighlightedRange`, `AnomalyPointsLayer`) compose as children. Custom overlays read `useChartLayout()` / `useChartHover()`. [docs/overlays.md](./src/docs/overlays.md)
- The built-in `DefaultTooltip` is configured through `config.tooltip`; a `tooltip` render prop replaces its content. [docs/tooltips.md](./src/docs/tooltips.md)
- `config.legend` renders the built-in legend: plain click isolates, modifier click toggles. [docs/legend.md](./src/docs/legend.md)
- Axis format, baseline, min/max, multi-axis, grid and axis-line chrome, margins. [docs/axes.md](./src/docs/axes.md)
- Bar layouts, per-bar overrides, `minBarSize`, `trackData`, combo charts. [docs/bars.md](./src/docs/bars.md)
- `onPointClick`, drag-to-zoom (`onDateRangeZoom`), 2D brush (`onAreaSelect`), touch. [docs/interactions.md](./src/docs/interactions.md)

## Gotchas that bite

- A duplicate label draws the series backwards. Use ISO dates, not display labels.
- In percent layouts every formatter receives a 0..1 fraction; `ValueLabelContext.rawValue` has the original.
- Bar and combo charts ignore `yAxis.min` / `max` on purpose. Pin `valueDomain` instead.
- A pinned tooltip's `onRowClick` only fires when `config.tooltip.pinnable` is set. Call `ctx.onUnpin()` before opening a modal from it.
- On stacked bars, describe the hovered segment from `TooltipContext.hoveredSeriesKey`, not `seriesData[0]`.
- A secondary axis with a fixed meaning (0..1, 0..100) needs `min` / `max` pinned, or a reference line above its data falls off the plot.
- A custom overlay with its own hover or click needs `data-hog-charts-interactive-overlay` on its root, or the chart's tooltip fights it for the cursor.
- The top/bottom legend height cap only resolves against an explicit container `height`, not a flex-derived one.
- A new `Series[]` reference every render recomputes the scales and repaints the canvas. Memoize.

## Testing

Import helpers from `@posthog/quill-charts/testing` (jsdom only): `getHogChart` reads rendered overlays through stable `data-attr` hooks, `renderHogChart` adds tooltip-context capture for library tests, `hoverAtIndex` / `clickAtIndex` / `hoverUntilTooltip` / `dragSelection` drive gestures, and `createDefaultTooltipAccessor` reads the built-in tooltip. The `data-attr` selectors are a public contract. [docs/TESTING.md](./src/docs/TESTING.md)

## Docs index

| Doc                                                | Covers                                                                                                                 |
| -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| [src/README.md](./src/README.md)                   | Public surface, setup, theme, custom tooltip and overlay basics, sparkline                                             |
| [docs/chart-types.md](./src/docs/chart-types.md)   | Per-chart behavior: scatter, funnel, slope, pie, box plot, heatmap, sparkline, metric card                             |
| [docs/axes.md](./src/docs/axes.md)                 | Defaults, grid and axis chrome, x-axis labels, y format, baseline and range, multi-axis, margins, blank-plot diagnosis |
| [docs/bars.md](./src/docs/bars.md)                 | Layouts, per-bar overrides, `minBarSize`, `trackData`, hit-testing, trend lines, combo                                 |
| [docs/tooltips.md](./src/docs/tooltips.md)         | `config.tooltip`, `DefaultTooltip` props, custom pieces, context fields, touch                                         |
| [docs/legend.md](./src/docs/legend.md)             | Click model, controlled state, visibility groups, row rendering, layout caps                                           |
| [docs/overlays.md](./src/docs/overlays.md)         | Built-in overlays and writing a custom one                                                                             |
| [docs/interactions.md](./src/docs/interactions.md) | Clicks, drag-to-zoom, 2D brush, hover                                                                                  |
| [docs/CONTRIBUTING.md](./src/docs/CONTRIBUTING.md) | Layers, conventions, adding a chart type                                                                               |
| [docs/TESTING.md](./src/docs/TESTING.md)           | The accessor contract and test recipes                                                                                 |

## Maintenance

When adding or changing a chart, overlay, or config option: write the JSDoc on the prop, add or update a story next to the component, and update the matching topic doc under `src/docs/` when the behavior spans more than one field. Add a row to this file only when the change alters which chart or approach a consumer should pick, or adds a gotcha. Do not append clauses to existing bullets here; this file stays a map.

Keep detailed library behavior here or in `src/docs/`.
The [consumer skill](../../../../.agents/skills/working-with-charts/SKILL.md) links to the relevant package docs and examples.
