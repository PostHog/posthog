# HogCharts

A pure rendering library for PostHog charts.
Components take typed data in, render a chart out — no business logic, no data fetching, no kea.

Built on Chart.js for canvas charts, with HTML/SVG renderers for non-canvas chart types.

## Status

Only `Line` is implemented so far. The remaining chart types have typed props defined in `types.ts` but no components yet.

## Usage

```tsx
import { Line } from 'lib/hog-charts'

;<Line data={[{ label: 'Users', data: [100, 200, 300, 250] }]} labels={['Mon', 'Tue', 'Wed', 'Thu']} />
```

All props are defined in [`types.ts`](./types.ts).
The key types are `Series` (data for time-series charts), `LineProps`, and `BaseChartProps` (shared across all chart types).

## Architecture

This library replaces the current rendering layer where insight-specific components (e.g. `<ActionsLineGraph />`, `<ActionsPie />`, `<FunnelBarHorizontal />`) each talk directly to Chart.js, D3, or raw HTML.
HogCharts sits below the kea data logics and above the rendering engines:

1. **Components** (`components/`) — React components that accept typed props. One per chart type.
2. **Adapters** (`adapters/`) — transform HogCharts props into Chart.js config objects (canvas charts) or structured data for HTML/SVG renderers.
3. **Utils** (`utils/`) — theming and formatting helpers, shared with `lib/charts`.

## Theming

```tsx
import { mergeTheme } from 'lib/hog-charts'

const custom = mergeTheme({
  colors: ['#FF6B6B', '#4ECDC4', '#45B7D1'],
})

<Line theme={custom} data={series} labels={labels} />
```

Use `seriesColor(theme, index)` to resolve the color for a given series index.

## Chart types

| Type   | Renderer        |
| ------ | --------------- |
| Line   | Chart.js canvas |
| Bar    | Chart.js canvas |
| Pie    | Chart.js canvas |
| Funnel | HTML / CSS      |
| Number | HTML / CSS      |
| Paths  | SVG             |

A `HogChart` dispatcher component will select the right renderer based on a `type` discriminant.
