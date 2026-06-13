# Charts — Agent Reference

Quick-reference for AI agents using `@posthog/quill-charts`. Canvas-rendered charts, themed via quill design tokens. Ships no CSS — colors come from CSS variables at runtime.

## Choosing a chart

| Chart               | Use when                                                                                                                        |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| LineChart           | Categorical x-axis trends; area fills, fill-between (confidence ribbons)                                                        |
| BarChart            | Categorical comparisons — `barLayout: 'stacked' \| 'grouped' \| 'percent'`, `axisOrientation: 'horizontal'` for horizontal bars |
| TimeSeriesLineChart | Time-indexed labels (ISO strings) with timezone/interval-aware x-axis                                                           |
| TimeSeriesBarChart  | Same x-axis handling, bar rendering; supports per-series `yAxisId` axes                                                         |
| PieChart            | Part-of-whole, one value per series; `innerRadiusRatio` for donut + `centerLabel`                                               |
| BoxPlot             | Distribution summaries — `{ min, p25, median, mean, p75, max }` per label                                                       |
| Sparkline           | Tiny inline trend from a flat `number[]` — no axes, no series structure                                                         |
| MetricCard          | Headline number + sparkline + change pill (dashboard stat tiles)                                                                |

## Theme wiring

```tsx
import { useChartTheme } from '@posthog/quill-charts'

const theme = useChartTheme() // reads CSS vars, tracks light/dark switches
<LineChart series={series} labels={labels} theme={theme} />
```

- Series colors come from `--data-color-1..15` (ordered categorical palette from `@posthog/quill-tokens`); chrome from `--color-graph-axis-label` / `--color-graph-axis-line` / `--color-graph-crosshair`.
- `themeFromCssVars()` is the one-shot non-hook version; `DEFAULT_CHART_COLORS` is the no-DOM fallback (kept in sync with tokens by a CI-enforced test).
- Omit `color` on a series to get palette assignment by index — preferred. Explicit `color` accepts hex or `var(--...)`.

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
- `ReferenceLine` variants: `goal` (dashed grey), `alert` (dashed red), `marker` (solid thin).
- `ValueLabels` formatter gets `(value, seriesIndex, dataIndex, context)`; in percent layouts `value` is a 0–1 fraction — use `context.rawValue` for the original.
- `Legend` is presentational: pass `items`, `onItemClick`, `hiddenKeys` — filtering series is the caller's state.
- y-axis `format`: `numeric | short | percentage | percentage_scaled | currency | duration | duration-ms`, plus `prefix`/`suffix`.

## Tooltips

The built-in tooltip handles most cases — **reach for a custom `tooltip` render prop only when you need a fundamentally different layout.** By default it formats each value with the y-axis tick formatter (so tooltip and axis agree) and renders non-finite values (NaN gap points) as an em dash.

```tsx
<TimeSeriesLineChart
  series={series}
  labels={labels}
  theme={theme}
  config={{
    yTickFormatter: (ms) => formatMs(ms),
    tooltip: {
      // Override only to format the tooltip differently from the axis; otherwise omit.
      valueFormatter: (ms) => formatMs(ms),
      // Append a contextual footer without rebuilding the whole tooltip.
      renderExtra: (ctx) => <div className="mt-1 opacity-70">{ctx.dataIndex} calls</div>,
    },
  }}
/>
```

- `config.tooltip.valueFormatter` — defaults to the resolved y-axis formatter; set it only to diverge from the axis. Non-finite values always render as `—` (don't special-case NaN yourself).
- `config.tooltip.renderExtra(ctx)` — extra content below the series rows (footers, context).
- A custom `tooltip` render prop still gets `ctx.formatValue` for axis-consistent formatting.

## Maintenance

When adding or changing a chart, overlay, or config option, update this guide in the same PR and add a story next to the component.
