# hog-charts

PostHog's canvas-based charting library, used for trends, dashboards, and any in-app chart that needs to render thousands of points smoothly. D3 powers the scales; the canvas does the drawing; React handles overlays.

```tsx
import { LineChart } from '@posthog/quill-charts'
import type { ChartTheme, Series } from '@posthog/quill-charts'

const SERIES: Series[] = [{ key: 'a', label: 'A', data: [10, 20, 30] }]
const LABELS = ['Mon', 'Tue', 'Wed']
const THEME: ChartTheme = { colors: ['#1f77b4'], backgroundColor: '#ffffff' }

;<LineChart series={SERIES} labels={LABELS} theme={THEME} />
```

## Setup

**Tokens (optional but recommended)** — load `@posthog/quill-tokens/color-system.css`
so `useChartTheme()` resolves the real quill palette and chrome. Without it you get
a sensible built-in fallback palette (see below), not the brand colors.

The built-in tooltip styles itself inline, so it renders correctly with no extra
setup. The rest of the library's chrome uses Tailwind utility classes — if you want
those generated for a non-PostHog host, add this package to your Tailwind
`@source`/content globs.

## Theme

Charts are **headless about color** — every chart takes a `ChartTheme` (`colors`
plus axis/grid/tooltip colors) and owns no palette of its own. Supply it however
you like, but the intended source is quill's design tokens.

`@posthog/quill-tokens` defines the data-viz palette as CSS vars
(`--data-color-1..15`, `--color-graph-*`). Read them into a `ChartTheme` with the
built-in helpers instead of hand-rolling per consumer:

```tsx
import { useChartTheme, BarChart } from '@posthog/quill-charts'

function MyChart() {
  const theme = useChartTheme() // re-reads on light/dark toggle
  return <BarChart series={SERIES} labels={LABELS} theme={theme} />
}
```

- `useChartTheme(opts?)` — React hook; re-reads the vars when the `class` / `theme`
  attribute flips on `<html>` or `<body>`.
- `themeFromCssVars(opts?)` — one-shot, non-React read.
- `DEFAULT_CHART_COLORS` — fallback palette used when the token vars aren't loaded
  (no quill-tokens stylesheet, or SSR). Without tokens loaded you get this palette,
  not black. Load `@posthog/quill-tokens/color-system.css` to get the real tokens.

Both helpers read from `document.body` by default. If you use the **scoped** token
build (vars gated behind `[data-quill]`) and quill isn't mounted on `<body>`, pass
`root` pointing inside the scoped subtree: `useChartTheme({ root: myQuillEl })`.

## Series

- `series.overlay` (default `false`): marks an auxiliary series derived from primary data — trend lines and moving averages. Excluded from stack computation and from the y-axis baseline calculation, so a trendline projection won't drag the axis below 0 when the underlying data is non-negative. (CI bands are not overlays — they represent real data uncertainty whose range should still influence the axis.)

`series.visibility` controls where a series appears:

- `excluded` (default `false`): fully excludes the series — no rendering, no scale contribution, no tooltip row, no hit-testing.
- `tooltip` (default `true`): when `false`, the series still renders and participates in scales and hit-testing, but is omitted from `TooltipContext.seriesData` so it doesn't appear as a tooltip row.
- `valueLabel` (default `true`): when `false`, the `ValueLabels` overlay skips this series.

## Custom tooltip

Pass a render prop to `tooltip`. It receives `TooltipContext` — `seriesData`, `label`, `dataIndex`, `position`, etc. Omit to use the built-in `DefaultTooltip`.

```tsx
<LineChart
  series={SERIES}
  labels={LABELS}
  theme={THEME}
  tooltip={(ctx) => <MyTooltip label={ctx.label} rows={ctx.seriesData} />}
/>
```

## Drag-to-zoom

Pass `onDateRangeZoom` to let the user drag a horizontal range across the plot.
The chart emits `{ startLabel, endLabel, startIndex, endIndex }` from the
labels array — it does not manage zoom state itself, so the parent decides
what to do with the range (typically updating a date filter).

```tsx
<TimeSeriesLineChart
  series={SERIES}
  labels={LABELS}
  theme={THEME}
  onDateRangeZoom={({ startLabel, endLabel }) => updateDateRange(startLabel, endLabel)}
/>
```

The cursor switches to `crosshair` while enabled, except over an
actionable point (`onPointClick` is set) where it stays `pointer`. A
plain click without movement still pins the tooltip or fires `onPointClick`.

## Custom overlays

Render any React component as a child of the chart and read layout / hover state through hooks:

- `useChartLayout()` — scales, dimensions, theme, resolved values. Doesn't re-render on hover.
- `useChartHover()` — hovered data point. Re-renders on every mousemove.
- `useChart()` — both, kept for back-compat. Use the granular hooks above unless you genuinely need both shapes.

```tsx
function GoalLine() {
  const { scales } = useChartLayout()
  const y = scales.y(100)
  return <div style={{ position: 'absolute', top: y, left: 0, right: 0, borderTop: '1px dashed' }} />
}

;<LineChart series={SERIES} labels={LABELS} theme={THEME}>
  <GoalLine />
</LineChart>
```

## Sparkline

`Sparkline` is an axis-less line+area preset over `LineChart`, intended as a
compact "trend at a glance" building block. It hides both axes and the
tooltip, draws the area with a vertical gradient fill, and exposes
`onHoverIndexChange` so consumers can drive a hover-following headline
without subscribing to `useChartHover` directly.

```tsx
import { Sparkline } from '@posthog/quill-charts'
;<Sparkline data={[4200, 5100, 4700, /* … */ 8800]} theme={THEME} />
```

## More

- Building a new chart type, library architecture, conventions → [docs/CONTRIBUTING.md](./docs/CONTRIBUTING.md)
- Writing tests against a chart, or against code that uses one → [docs/TESTING.md](./docs/TESTING.md)
