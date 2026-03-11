# HogCharts

A typed React charting library built on Chart.js.
Components take data in, render a chart out — no business logic, no data fetching.

## Usage

```tsx
import { Line } from 'lib/hog-charts'
;<Line data={[{ label: 'Users', data: [100, 200, 300, 250] }]} labels={['Mon', 'Tue', 'Wed', 'Thu']} />
```

All props are defined in [`types.ts`](./types.ts).
The key types are `Series`, `LineProps`, and `BaseChartProps`.

## Architecture

1. **Components** (`components/`) — React components that accept typed props. One per chart type.
2. **Adapters** (`adapters/`) — transform component props into Chart.js config objects.
3. **Utils** (`utils/`) — theming and formatting helpers.

## Theming

Every component ships with sensible defaults.
To override, pass a partial theme via the `theme` prop:

```tsx
<Line data={series} labels={labels} theme={{ colors: ['#FF6B6B', '#4ECDC4', '#45B7D1'] }} />
```

For a fully resolved theme object outside a component, use `mergeTheme` and `seriesColor`:

```ts
import { mergeTheme, seriesColor } from 'lib/hog-charts'

const theme = mergeTheme({ colors: ['#FF6B6B', '#4ECDC4'] })
seriesColor(theme, 0) // '#FF6B6B'
```

## Chart types

Currently only `Line` is implemented. More chart types will be added over time.
