# Insight test harness

A test wrapper for rendering insight components with mocked data and a chart inspection API.

## Quick start

```tsx
import { renderInsight, waitForChart, buildTrendsQuery } from './index'

renderInsight({
  query: buildTrendsQuery({
    series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
  }),
})

const chart = await waitForChart(1) // waits until 1 series is rendered
expect(chart.series('$pageview').data).toEqual([45, 82, 134, 210, 95])
```

## `renderInsight(props?)`

Renders an `InsightViz` component with mocked API responses.

| Prop            | Type                | Description                                              |
| --------------- | ------------------- | -------------------------------------------------------- |
| `query`         | `TrendsQuery`       | Query to render (defaults to a `$pageview` trends query) |
| `showFilters`   | `boolean`           | Show filter controls (interval, breakdown, etc.)         |
| `mocks`         | `SetupMocksOptions` | Override event/property definitions and property values  |
| `mockResponses` | `MockResponse[]`    | Custom query response matchers                           |

## Chart API

`getChart(index?)` returns a `Chart` for the most recently rendered chart (or a specific one by index).
`waitForChart(expectedSeries?)` polls until a chart renders with the expected number of series.

### Chart

| API                    | Description                                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------------- |
| `series(nameOrIndex)`  | Get a series by label or index                                                              |
| `seriesCount`          | Number of datasets                                                                          |
| `seriesNames`          | Array of series labels                                                                      |
| `value(series, point)` | Single data point — series by name/index, point by index or label (`value('Spike', 'Thu')`) |
| `labels`               | X-axis label array                                                                          |
| `label(index)`         | Single label by index                                                                       |
| `type`                 | Chart type (`'line'`, `'bar'`, etc.)                                                        |
| `axes`                 | Axis accessors (`axes.x`, `axes.y`, or any custom axis)                                     |
| `config`               | Raw `ChartConfig` escape hatch                                                              |

### Series

| API               | Description                            |
| ----------------- | -------------------------------------- |
| `label`           | Series name                            |
| `data`            | Number array                           |
| `at(index)`       | Single data point with bounds checking |
| `hidden`          | Whether the series is hidden           |
| `borderColor`     | Line/border color                      |
| `backgroundColor` | Fill color                             |

### Axis

| API                | Description                                 |
| ------------------ | ------------------------------------------- |
| `display`          | Whether the axis is visible                 |
| `type`             | Scale type (`'linear'`, `'category'`, etc.) |
| `stacked`          | Whether stacking is enabled                 |
| `position`         | Axis position (`'left'`, `'bottom'`, etc.)  |
| `tickLabel(value)` | Runs the tick formatter callback            |

## Interactions

When `showFilters: true`, you can simulate user interactions:

```tsx
import { series, breakdown, interval, display, compare } from './index'

await series.select('Napped') // pick an event from the series dropdown
await breakdown.set('hedgehog') // add a breakdown property
await interval.set('week') // change the time interval
await display.set('Bar chart') // change chart display type
await compare.enable() // enable compare to previous period
```

## Test data

Canned data lives in `test-data.ts`. The mock query handler automatically resolves
queries to the right data based on event name and breakdown property.

| Series                             | Data                                                 |
| ---------------------------------- | ---------------------------------------------------- |
| `$pageview`                        | `[45, 82, 134, 210, 95]` over Mon–Fri                |
| `Napped`                           | `[1, 3, 5, 8, 2]` over Mon–Fri                       |
| `Napped` + breakdown by `hedgehog` | 5 series (Spike, Bramble, Thistle, Conker, Prickles) |
