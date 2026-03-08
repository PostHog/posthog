# HogCharts

A type-safe React charting library built on Chart.js.
HogCharts provides a clean, progressively-disclosed API
that hides Chart.js internals behind strongly-typed components.

## Quick start

```tsx
import { Line, Bar, BigNumber, HogChart } from 'lib/hog-charts'

// Simple line chart
<Line
  data={[{ label: 'Users', data: [100, 200, 300, 250] }]}
  labels={['Mon', 'Tue', 'Wed', 'Thu']}
/>

// KPI number with comparison
<BigNumber value={42069} previousValue={38000} label="WAU" />

// Universal component (runtime dispatch by type)
<HogChart type="bar" data={data} labels={labels} stacked />
```

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full data flow
from backend API through kea logics to chart rendering.

## Chart components

12 typed chart components plus one universal `HogChart` dispatcher.

| Component | Props type | Rendering |
| --- | --- | --- |
| `Line` | `LineProps` | Canvas (Chart.js) |
| `Bar` | `BarProps` | Canvas (Chart.js) |
| `Area` | `AreaProps` | Canvas (Chart.js) |
| `Pie` | `PieProps` | Canvas (Chart.js) |
| `BoxPlot` | `BoxPlotProps` | Canvas (Chart.js) |
| `Lifecycle` | `LifecycleProps` | Canvas (Chart.js) |
| `BigNumber` | `NumberProps` | HTML |
| `Funnel` | `FunnelProps` | HTML |
| `Retention` | `RetentionProps` | HTML table |
| `Paths` | `PathsProps` | SVG |
| `WorldMap` | `WorldMapProps` | SVG |
| `Heatmap` | `HeatmapProps` | HTML grid |
| `HogChart` | `HogChartProps` | Dispatches to above |

`HogChart` accepts a discriminated union keyed on `type`:

```tsx
<HogChart
  type="line"
  data={[{ label: 'Revenue', data: [10, 20, 30] }]}
  labels={['Jan', 'Feb', 'Mar']}
  cumulative
/>
```

## Data types

### Series (time-series charts)

All time-series charts (`Line`, `Bar`, `Area`, `Lifecycle`, `Stickiness`) share the `Series` type:

```ts
interface Series {
  label: string
  data: number[]
  color?: string
  hidden?: boolean
  meta?: Record<string, unknown>  // opaque — passed through to tooltips/clicks
  displayType?: 'line' | 'bar'
  yAxisPosition?: 'left' | 'right'
  trendLine?: boolean
  fill?: boolean
  lineStyle?: 'solid' | 'dashed' | 'dotted'
  hideFromTooltip?: boolean
}
```

**ComparisonSeries** extends `Series` with a `compareLabel` field
for previous-period overlays.

### Chart-specific data types

```ts
// Pie / Donut
interface PieSlice { label: string; value: number; color?: string; meta?: Record<string, unknown> }

// Funnel
interface FunnelStep { label: string; count: number; breakdown?: { label: string; count: number }[]; medianTime?: number }

// Retention — index 0 is cohort size, rest are retention counts
interface RetentionCohort { label: string; date: string; values: number[] }

// Paths (Sankey)
interface PathNode { name: string; count: number }
interface PathLink { source: string; target: string; value: number; averageTime?: number }

// World map
interface MapDataPoint { code: string; value: number; label?: string }  // code: ISO 3166-1 alpha-2

// Box plot
interface BoxPlotDatum { label: string; min: number; q1: number; median: number; q3: number; max: number; mean?: number; outliers?: number[] }

// Heatmap
interface HeatmapCell { x: string | number; y: string | number; value: number }

// Lifecycle
interface LifecycleBucket { label: string; new: number; returning: number; resurrecting: number; dormant: number }
```

## Common props (BaseChartProps)

Every chart component accepts these base props:

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `width` | `number \| string` | `'100%'` | Chart width |
| `height` | `number \| string` | `300` | Chart height |
| `theme` | `Partial<HogChartTheme>` | `defaultTheme` | Theme overrides |
| `legend` | `LegendConfig` | — | Legend position and max items |
| `tooltip` | `TooltipConfig` | — | Tooltip behavior and custom render |
| `className` | `string` | — | CSS class |
| `animate` | `boolean` | `false` | Enable animations |
| `ariaLabel` | `string` | — | Accessibility label |
| `onClick` | `(point: ClickEvent) => void` | — | Click handler |

## Axes

```ts
type AxisFormat = 'number' | 'compact' | 'percent' | 'duration'
               | 'duration_ms' | 'date' | 'datetime' | 'none'

interface AxisConfig {
  label?: string
  format?: AxisFormat
  prefix?: string         // e.g. "$"
  suffix?: string         // e.g. "%"
  decimalPlaces?: number
  scale?: 'linear' | 'logarithmic'
  startAtZero?: boolean
  gridLines?: boolean
  min?: number
  max?: number
}
```

Line, bar, and area charts accept `yAxis` as either
a single `AxisConfig` or a tuple `[AxisConfig, AxisConfig]` for dual y-axes.
Assign series to the right axis with `series.yAxisPosition = 'right'`.

## Decorations

### Goal lines

```tsx
<Line
  data={series}
  labels={labels}
  goalLines={[
    { value: 1000, label: 'Target', style: 'dashed', color: '#F04F58' },
  ]}
/>
```

### Annotations

```tsx
<Line
  data={series}
  labels={labels}
  annotations={[
    { at: '2024-03-15', label: 'Launch', description: 'v2.0 released' },
  ]}
/>
```

## Theming

```ts
import { defaultTheme, mergeTheme, hogColors } from 'lib/hog-charts'

const custom = mergeTheme({
  colors: ['#FF6B6B', '#4ECDC4', '#45B7D1'],
  backgroundColor: '#1a1a2e',
  tooltipBackground: '#16213e',
})

<Line theme={custom} data={series} labels={labels} />
```

Default theme:

| Key | Default |
| --- | --- |
| `colors` | 15-color accessible palette (`hogColors`) |
| `fontFamily` | System font stack |
| `fontSize` | 12 |
| `backgroundColor` | transparent |
| `axisColor` | `#94949480` |
| `gridColor` | `#94949420` |
| `goalLineColor` | `#F04F58` |
| `tooltipBackground` | `#1D1F27` |
| `tooltipColor` | `#EEEEEE` |
| `tooltipBorderRadius` | 8 |

Use `seriesColor(theme, index)` to resolve the color for a given series index.

## Tooltips

### Default tooltip

Shared by default (shows all series at the hovered x position).

### Custom tooltip

```tsx
<Line
  data={series}
  labels={labels}
  tooltip={{
    shared: true,
    formatValue: (value, seriesIndex) => `$${value.toFixed(2)}`,
    render: (context) => (
      <div>
        <strong>{context.label}</strong>
        {context.points.map((p) => (
          <div key={p.seriesIndex}>
            {p.seriesLabel}: {p.value}
          </div>
        ))}
      </div>
    ),
    onHide: () => console.log('tooltip hidden'),
  }}
/>
```

`TooltipContext` provides:

| Field | Type | Description |
| --- | --- | --- |
| `label` | `string` | X-axis label |
| `points` | `TooltipPoint[]` | All points at this x position |
| `position` | `{ x, y }` | Canvas-relative coordinates |
| `chartBounds` | `DOMRect` | Chart container bounds |

Each `TooltipPoint` has `seriesIndex`, `pointIndex`, `value`,
`seriesLabel`, `color`, and `meta`.

## Click events

```tsx
<Bar
  data={series}
  labels={labels}
  onClick={(event) => {
    console.log(event.seriesIndex, event.pointIndex, event.value)
    console.log(event.meta) // your custom metadata
  }}
/>
```

## Chart-specific features

### Line

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `cumulative` | `boolean` | `false` | Running total mode |
| `interpolation` | `'linear' \| 'smooth' \| 'step'` | `'linear'` | Curve style |
| `showDots` | `boolean \| 'auto'` | `'auto'` | Show points (auto = shown when ≤ 30 points) |
| `lineWidth` | `number` | `2` | Line width |
| `stacked` | `boolean` | `false` | Stack series |
| `percentStacked` | `boolean` | `false` | 100% stacked (implies stacked) |
| `isArea` | `boolean` | `false` | Fill under series |
| `fillOpacity` | `number` | `0.5` | Fill opacity |
| `crosshair` | `boolean` | `true` | Show vertical crosshair on hover |
| `incompletePoints` | `number` | `0` | Trailing dotted points for in-progress data |
| `highlightSeriesIndex` | `number \| null` | — | Highlight a specific series |
| `compare` | `ComparisonSeries[]` | — | Previous period overlay |
| `dates` | `(string \| number)[]` | — | Raw date strings for smart tick formatting |
| `interval` | `ChartInterval` | — | Time interval for tick formatting |

### Bar

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `stacked` | `boolean` | `false` | Stack bars |
| `percentStacked` | `boolean` | `false` | 100% stacked |
| `orientation` | `'vertical' \| 'horizontal'` | `'vertical'` | Bar direction |
| `borderRadius` | `number` | `4` | Corner rounding |
| `barGap` | `number` | `0.3` | Gap fraction (0-1) |

### Pie

| Prop | Type | Default | Description |
| --- | --- | --- | --- |
| `donut` | `boolean` | `true` | Donut or solid pie |
| `innerRadius` | `number` | `0.6` | Hole size (0-1) |
| `showLabels` | `boolean` | `true` | Show slice labels |
| `showValues` | `boolean` | `false` | Show values |

### BigNumber

```tsx
<BigNumber
  value={42069}
  previousValue={38000}  // shows +10.7% delta
  label="Weekly active users"
  format="compact"
  prefix="$"
/>
```

### Funnel

```tsx
<Funnel
  steps={[
    { label: 'Visit', count: 10000 },
    { label: 'Sign up', count: 3000 },
    { label: 'Purchase', count: 400, medianTime: 86400 },
  ]}
  layout="horizontal"
  showConversionRates
  showTime={false}
/>
```

### Retention

```tsx
<Retention
  data={[
    { label: 'Week 0', date: '2024-01-01', values: [1000, 450, 200, 150] },
    { label: 'Week 1', date: '2024-01-08', values: [900, 400, 180] },
  ]}
  periodLabels={['Week 0', 'Week 1', 'Week 2', 'Week 3']}
  period="week"
  showPercentages
/>
```

### Paths

```tsx
<Paths
  nodes={[
    { name: '/home', count: 5000 },
    { name: '/pricing', count: 3000 },
    { name: '/signup', count: 1000 },
  ]}
  links={[
    { source: '/home', target: '/pricing', value: 2000 },
    { source: '/pricing', target: '/signup', value: 800 },
  ]}
  maxPaths={50}
/>
```

### World map

```tsx
<WorldMap
  data={[
    { code: 'US', value: 45000, label: 'United States' },
    { code: 'GB', value: 12000 },
  ]}
  colorRange={['#E8F4FD', '#1D4ED8']}
/>
```

### Heatmap

```tsx
<Heatmap
  data={cells}
  xLabels={['Mon', 'Tue', 'Wed']}
  yLabels={['9am', '10am', '11am']}
  colorRange={['#f0f0f0', '#ff0000']}
  showValues
/>
```

### Lifecycle

```tsx
<Lifecycle
  data={[
    { label: 'Jan 1', new: 100, returning: 500, resurrecting: 50, dormant: -200 },
    { label: 'Jan 2', new: 120, returning: 480, resurrecting: 60, dormant: -180 },
  ]}
  labels={['Jan 1', 'Jan 2']}
  statusColors={{ new: '#35C759', dormant: '#F04F58' }}
  visibleStatuses={['new', 'returning', 'resurrecting', 'dormant']}
/>
```

## Formatting utilities

```ts
import { formatValue, computeDelta } from 'lib/hog-charts'

formatValue(1234, 'compact')     // "1.2K"
formatValue(0.456, 'percent')    // "45.6%"
formatValue(3723, 'duration')    // "1h 2m"

computeDelta(420, 380)           // 0.1053 (10.53%)
```
