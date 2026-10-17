# Overlays on stock charts

Every chart in `@posthog/quill-charts` renders its `children` in a React layer above the `<canvas>`, inside the chart's context.
Anything placed there can read the chart's scales and hover state, so a mark the chart does not draw itself is a small component, not a new chart.
Hover, the tooltip, the axes and the legend stay stock.

Reach for this rung when the request is a stock chart with one more thing on it: a target, a release, an incident, a callout, a readout.

## What the context gives you

```tsx
const { scales, dimensions, series, labels, theme } = useChartLayout()
const { hoverIndex } = useChartHover()
```

- `scales.x(label)` and `scales.y(value)` map data to pixels in the chart wrapper's coordinate space, so an absolutely positioned element at `left: scales.x(label), top: scales.y(value)` lands on the point.
- `dimensions` has `plotLeft`, `plotTop`, `plotWidth`, `plotHeight` for anything anchored to the plot's edges.
- `series` carries resolved colors: `series[i].color` is the palette color the line or bar was drawn with.
- `useChartLayout()` does not re-render on mouse move; `useChartHover()` does. Read hover only in the component that needs it.
- The overlay component must be a child of the chart. Rendered anywhere else, these hooks throw.

## Shipped overlays

- `ReferenceLine`: a horizontal line at a y value or a vertical line at a label. `variant` is `goal` (dashed grey), `alert` (dashed red) or `marker` (solid thin). `label` and `labelPosition` annotate it; `fillSide` tints the half-plane on one side.
- `ReferenceLines lines={[...]}`: several at once.
- `HighlightedRange start end`: a translucent box over a label or index range, for an incident window or the rows a paired list is showing.

Both take `color` as a CSS string and do resolve `var(--…)`, unlike series colors.

## Three examples

The data setup is shared:

```tsx
import {
  HighlightedRange,
  ReferenceLine,
  TimeSeriesLineChart,
  TimeSeriesBarChart,
  useChartHover,
  useChartLayout,
  useChartTheme,
  type Series,
} from '@posthog/quill-charts'
import dayjs from 'dayjs'

const DAYS = Array.from({ length: 30 }, (_, i) => dayjs('2026-09-15').add(i, 'day').format('YYYY-MM-DD'))
const SIGNUPS = DAYS.map((_, i) =>
  Math.round(120 + 40 * Math.sin(i / 4) + (i > 18 && i < 23 ? -60 : 0) + (i % 7 === 5 ? 35 : 0))
)
const SERIES: Series[] = [{ key: 'signups', label: 'Signups', data: SIGNUPS }]
const config = {
  xAxis: { interval: 'day' as const, tickFormatter: (d: string) => dayjs(d).format('MMM D') },
  tooltip: { placement: 'top' as const },
}
```

### A target, a release and an incident

Three shipped overlays and no drawing. The goal line tints everything above the target; the release is a vertical marker at a label; the incident is a range.

```tsx
// 1. Stock overlays: a release marker, an incident window, a goal line with a filled side.
export function AnnotatedTrend() {
  const theme = useChartTheme()
  return (
    <TimeSeriesLineChart theme={theme} series={SERIES} labels={DAYS} config={config}>
      <ReferenceLine value={150} label="Target" variant="goal" fillSide="above" style={{ fillOpacity: 0.06 }} />
      <ReferenceLine value="2026-09-24" orientation="vertical" label="v1.42" variant="marker" />
      <HighlightedRange start="2026-10-03" end="2026-10-07" color={theme.colors[4]} fillOpacity={0.12} />
    </TimeSeriesLineChart>
  )
}
```

### Callouts on the peaks

A custom overlay. It finds local maxima in the series and pins a pill above each with the chart's own scales. `pointer-events-none` keeps it from stealing the hover from the canvas.

```tsx
// 2. A custom overlay: callouts positioned with the chart's own scales.
function PeakCallouts() {
  const { scales, series, labels, theme } = useChartLayout()
  const data = series[0].data
  const peaks = data
    .map((v, i) => (i > 0 && i < data.length - 1 && v > data[i - 1] && v > data[i + 1] && v > 150 ? i : -1))
    .filter((i) => i >= 0)
  return (
    <>
      {peaks.map((i) => (
        <div
          key={i}
          className="pointer-events-none absolute -translate-x-1/2 -translate-y-full rounded-full px-1.5 py-0.5 text-[10px] font-semibold tabular-nums"
          style={{
            left: scales.x(labels[i]),
            top: scales.y(data[i]) - 8,
            backgroundColor: series[0].color,
            color: theme.backgroundColor ?? '#000',
          }}
        >
          {data[i]}
        </div>
      ))}
    </>
  )
}

export function TrendWithCallouts() {
  const theme = useChartTheme()
  return (
    <TimeSeriesLineChart theme={theme} series={SERIES} labels={DAYS} config={config}>
      <PeakCallouts />
    </TimeSeriesLineChart>
  )
}
```

### A readout that follows the hover

`useChartHover()` gives the hovered index; the overlay compares it with the same weekday a week earlier and prints the change above the plot. Nothing renders until the user hovers.

```tsx
// 3. A hover-linked overlay: a strip that compares the hovered bar with the same weekday a week before.
function WeekOverWeek() {
  const { hoverIndex } = useChartHover()
  const { series, labels, dimensions } = useChartLayout()
  if (hoverIndex < 7) return null
  const now = series[0].data[hoverIndex]
  const then = series[0].data[hoverIndex - 7]
  const delta = ((now - then) / then) * 100
  return (
    <div
      className="pointer-events-none absolute text-xs text-muted-foreground"
      style={{ left: dimensions.plotLeft, top: dimensions.plotTop - 2 }}
    >
      {dayjs(labels[hoverIndex]).format('ddd D MMM')} vs a week earlier:{' '}
      <strong className={delta >= 0 ? 'text-success-foreground' : 'text-destructive-foreground'}>
        {delta >= 0 ? '+' : ''}
        {delta.toFixed(0)}%
      </strong>
    </div>
  )
}

export function BarsWithWeekOverWeek() {
  const theme = useChartTheme()
  return (
    <TimeSeriesBarChart theme={theme} series={SERIES} labels={DAYS} config={{ ...config, barCornerRadius: 2 }}>
      <WeekOverWeek />
    </TimeSeriesBarChart>
  )
}
```

## Rules

- Position with `scales` and `dimensions`, never with hardcoded pixels or percentages: the chart resizes with its card.
- `pointer-events-none` on anything that sits over the plot, or it blocks the hover.
- A chart-level annotation such as a target or a release belongs in a `ReferenceLine`; write a custom overlay only for marks the shipped ones cannot express.
- Colors from `series[i].color` and `theme`, so the overlay matches the series it annotates.
