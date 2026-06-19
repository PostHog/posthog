# Charts — Agent Reference

Quick-reference for AI agents using `@posthog/quill-charts`. Canvas-rendered charts, themed via quill design tokens. Ships no CSS — colors come from CSS variables at runtime.

## Choosing a chart

| Chart               | Use when                                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| LineChart           | Categorical x-axis trends; area fills, fill-between (confidence ribbons)                                                        |
| BarChart            | Categorical comparisons — `barLayout: 'stacked' \| 'grouped' \| 'percent'`, `axisOrientation: 'horizontal'` for horizontal bars |
| ComboChart          | Mixed bar/line/area series on one band x-axis — set `Series.type`; vertical-only, `barLayout: 'stacked' \| 'grouped'`           |
| TimeSeriesLineChart | Time-indexed labels (ISO strings) with timezone/interval-aware x-axis                                                           |
| TimeSeriesBarChart  | Same x-axis handling, bar rendering; supports per-series `yAxisId` axes                                                         |
| PieChart            | Part-of-whole, one value per series; `innerRadiusRatio` for donut + `centerLabel`                                               |
| BoxPlot             | Distribution summaries — `{ min, p25, median, mean, p75, max }` per label                                                       |
| Sparkline           | Tiny inline trend from a flat `number[]` — no axes, no series structure                                                         |
| MetricCard          | Headline number + sparkline + change pill (dashboard stat tiles)                                                                |
| SlopeChart          | Change between two points (slopegraph) — one line per series, left "before" → right "after"; `data: [start, end]`               |

## Theme wiring

```tsx
import { useChartTheme } from '@posthog/quill-charts'

const theme = useChartTheme() // reads CSS vars, tracks light/dark switches
<LineChart series={series} labels={labels} theme={theme} />
```

- Series colors come from `--data-color-1..15` (ordered categorical palette from `@posthog/quill-tokens`); chrome from `--color-graph-axis-label` / `--color-graph-axis-line` / `--color-graph-crosshair`.
- `themeFromCssVars()` is the one-shot non-hook version; `DEFAULT_CHART_COLORS` is the no-DOM fallback (kept in sync with tokens by a CI-enforced test).
- Omit `color` on a series to get palette assignment by index — preferred. Explicit `color` accepts hex or `var(--...)`.
- `theme.skipDraw` suppresses all canvas painting (static layer + hover overlay) while still mounting the `<canvas>` element. Use it for deterministic visual-snapshot tests where the async paint pipeline (ResizeObserver → requestAnimationFrame) races the screenshot — the chart renders blank but layout and DOM selectors are unaffected.

## Series shape (all multi-series charts)

```tsx
const series: Series[] = [
  { key: 'visits', label: 'Visits', data: [20, 35, 28] }, // data.length === labels.length
  { key: 'goal', label: 'Goal', data: [30, 30, 30], overlay: true }, // excluded from stacking
]
```

- `key` (React key + stacking identity), `label` (legend/tooltip), `data` are required.
- Line-only options: `points`, `stroke.pattern` (dashes/projections), `fill.opacity` / `fill.gradient` (area), `fill.lowerData` (ribbon).
- `yAxisId` scales a series against a second axis; `meta` carries arbitrary data into tooltips.

## Sizing

Charts fill their container and need a parent with real dimensions — a `0`-height flex child renders nothing. Give the wrapper an explicit height (`h-64`, `flex-1` in a sized column). Sparkline alone takes `height`/`width` props.

## Composition

```tsx
<TimeSeriesLineChart
  series={series}
  labels={isoLabels}
  theme={theme}
  config={{
    xAxis: { timezone: 'UTC', interval: 'day' },
    yAxis: { format: 'currency', currency: 'USD' },
  }}
>
  <ReferenceLine value={100} orientation="horizontal" variant="goal" label="Target" />
  <ValueLabels mode="stack-total" offset={8} />
</TimeSeriesLineChart>
```

- Overlays (`ReferenceLine`/`ReferenceLines`, `ValueLabels`, `AxisTitles`) compose as children.
- `DefaultTooltip` (the built-in tooltip, also usable from a custom `tooltip` render prop) takes optional `valueFormatter`, `showTotal`, `totalLabel`, `totalFormatter`. `valueFormatter` gets `(value, entry)` — the row's `seriesData` entry as a second arg — so each row can format with its own `series.meta` (e.g. per-column currency/duration). `showTotal` appends a footer row summing the visible series; it excludes `overlay` series (goal lines) from the sum and is suppressed when fewer than two summable series remain. `totalFormatter` formats the total (defaults to `valueFormatter` applied with the first summable row's entry); `totalLabel` defaults to `'Total'`. A formatter taking only `value` stays compatible — the extra arg is ignored.
- `ReferenceLine` variants: `goal` (dashed grey), `alert` (dashed red), `marker` (solid thin).
- `ValueLabels` formatter gets `(value, seriesIndex, dataIndex, context)`; in percent layouts `value` is a 0–1 fraction — use `context.rawValue` for the original.
- Every multi-series chart (`LineChart`, `BarChart`, `TimeSeriesLineChart`, `TimeSeriesBarChart`, `SlopeChart`) takes a `config.legend: ChartLegendConfig` (`{ show, position, align, gap, interactive, hiddenKeys, defaultHiddenKeys, onToggleSeries }`). With `show: true` the chart renders a built-in legend that, by default (`interactive`), is click-to-toggle: clicking a row hides that series (no draw, no scale contribution, no tooltip — the axes rescale into the freed space) while the row stays listed but dimmed so it can be restored. The chart owns the toggled-off state (uncontrolled); set `interactive: false` for a static legend, or pass `hiddenKeys` + `onToggleSeries` to control it yourself. Hidden by default. Toggling on time-series charts lists the user's series only (not derived trend lines / CI bands) — and hiding a series also hides everything derived from it (its CI band, moving average, and trend line), so no orphaned overlay floats over the gap.
- `Legend` (and `ChartLegend` for layout) is the lower-level presentational primitive: pass `items`, `onItemClick`, `hiddenKeys` — filtering series is the caller's state. Use it directly when the built-in `config.legend` can't express what you need (custom item order/labels). `useChartLegend(series, theme, config, items?)` is the shared hook the charts use — returns `visibleSeries` (hidden applied as `visibility.excluded`) plus `legendProps` to spread onto `<ChartLegend>`; `applyHiddenSeries` is the underlying helper. `LegendItem.secondaryLabel` shows muted trailing text (e.g. a slope chart's per-series change).
- `SlopeChart` config: `showSeriesLabels` (name beside each point; steepest line wins label collisions), `showStartLabels`/`showEndLabels` (defaults overridable per series via `meta.showStartLabel`/`showEndLabel`), `legend` (`{ show, position }`, rows carry the formatted change, ordered biggest-to-smallest by end value to match the lines' right-edge order), `valueFormatter`/`deltaFormatter`. The value axis is hidden by default — the start/end labels are the readout. The default tooltip orders its rows biggest-to-smallest by the hovered point's value (so many-breakdown tooltips match the lines' vertical order) and formats values with `valueFormatter` so they match the on-chart labels' units; pass your own `tooltip` to override. (`DefaultTooltip` itself takes an optional `valueFormatter` for the same reason — without it values fall back to `toLocaleString`.) Per-series `meta.incompleteEnd` dashes only the second half of that connector (the last point is the current incomplete period); the renderer splits the final segment at its midpoint via `stroke.partial.fromFraction`, so a two-point line needs no phantom interior point.
- `MetricCard` is a left-aligned tile. Pass `title={null}` to drop the title row — the header band collapses when there is no title and no change pill, and the subtitle row is omitted when there is no subtitle (and no `labels`), so a value-only card renders just the number. `changeSize="md"` renders a larger change pill (default `sm`); `changeInline` puts the pill beside the headline instead of in the header; `sparklineFill` makes the sparkline fill the card's remaining height instead of a fixed `sparklineHeight`. `subtitle` always wins (shown at rest and on hover); `restingSubtitle` (e.g. `'Avg'`) shows only at rest and yields to the hovered point's label on hover — pair it with a `value` that summarizes the series (average/total) so the headline reads as a summary until hovered. `hoverChangeFromPreviousPoint` keeps the supplied resting `change` pill at rest but, while hovering, swaps it for the hovered point's change vs the previous point (hidden at the first point).
- y-axis `format`: `numeric | short | percentage | percentage_scaled | currency | duration | duration-ms`, plus `prefix`/`suffix`.
- `onDateRangeZoom` (on `LineChart`/`TimeSeriesLineChart`/base `Chart`) enables x-axis drag-to-zoom: the user drags horizontally and the callback fires once with `{ startLabel, endLabel, startIndex, endIndex }` for the spanned range. The cursor switches to a crosshair when set. x-axis only — no effect on charts with a vertical interaction axis.

## Maintenance

When adding or changing a chart, overlay, or config option, update this guide in the same PR and add a story next to the component.
