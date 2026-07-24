# Insight testing

A test wrapper for rendering insight components (or any component that depends on insight infrastructure) with mocked data and a chart inspection API.

## What belongs in a harness test

Chart coverage is layered; a rendered harness test is the most expensive layer (~100ms per mount), so it only earns its place for what the cheaper layers can't see:

- **Storybook snapshot stories** own render smoke and visual states. Don't write "renders without crashing" tests — add a story instead.
- **quill-charts' own suite** owns chart mechanics (legend toggling, tooltip pinning, goal lines, value labels, axes). Don't re-test library behavior here.
- **Transforms/adapter unit tests** own the case matrix for pure logic (series construction, formatters, click-handler payloads) at ~1ms per case.
- **Harness tests** (this wrapper) own interaction and data wiring only: the right values reach the tooltip, clicks open the persons modal with the right actors, empty-state guards fire — one wiring test per chart-specific feature, not one per data variation.

## Quick start

```tsx
import { renderInsight, waitForChart, buildTrendsQuery } from './index'

renderInsight({
  query: buildTrendsQuery({
    series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
  }),
})

const chart = await waitForChart()
expect(chart.series('$pageview').data).toEqual([45, 82, 134, 210, 95])
```

## `renderInsight(props?)`

Renders a full `InsightViz` component with mocked API responses.
Handles all setup automatically — Kea context, common logics, and API mocks.

| Prop            | Type                | Description                                              |
| --------------- | ------------------- | -------------------------------------------------------- |
| `query`         | `TrendsQuery`       | Query to render (defaults to a `$pageview` trends query) |
| `showFilters`   | `boolean`           | Show filter controls (defaults to `false`)               |
| `mocks`         | `SetupMocksOptions` | Override event/property definitions and property values  |
| `mockResponses` | `MockResponse[]`    | Custom query response matchers                           |

By default only the chart renders — no filter editor UI.
Mounting the filter controls roughly doubles a test's runtime, so use `renderInsightPage` (same props, `showFilters` defaults to `true`) only when the test interacts with them.

## `renderWithInsights(props)`

Renders any component with insight mocks and Kea logics ready.
Use this when testing a component that contains insights internally
(e.g. a page that embeds `InsightViz`) rather than testing `InsightViz` directly.

```tsx
import { renderWithInsights } from './index'

renderWithInsights({
  component: <JourneyBuilder steps={steps} />,
  mockResponses: [{ match: (q) => q.kind === 'TrendsQuery', response: myTrendsData }],
})
```

| Prop            | Type                 | Description                                             |
| --------------- | -------------------- | ------------------------------------------------------- |
| `component`     | `React.ReactElement` | The component to render                                 |
| `mocks`         | `SetupMocksOptions`  | Override event/property definitions and property values |
| `mockResponses` | `MockResponse[]`     | Custom query response matchers                          |

## Chart API

`waitForChart()` waits for a new chart to render since the last call, then returns it.
Back-to-back calls after interactions always return fresh data.

`getChart(index?)` returns the most recently rendered chart (or a specific one by index)
without waiting.

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

Filter interactions need the filter controls mounted — render with `renderInsightPage` (or pass `showFilters: true`):

```tsx
import { series, breakdown, interval, display, compare } from './index'

await series.select('Napped') // pick an event from the series dropdown
await breakdown.set('hedgehog') // add a breakdown property
await interval.set('week') // change the time interval
await display.set('Bar chart') // change chart display type
await compare.enable() // enable compare to previous period
```

After any interaction, call `await waitForChart()` to get the updated chart.

## Test data

Canned data lives in `test-data.ts`. The mock query handler automatically resolves
queries to the right data based on event name and breakdown property.

| Series                             | Data                                                 |
| ---------------------------------- | ---------------------------------------------------- |
| `$pageview`                        | `[45, 82, 134, 210, 95]` over Mon–Fri                |
| `Napped`                           | `[1, 3, 5, 8, 2]` over Mon–Fri                       |
| `Napped` + breakdown by `hedgehog` | 5 series (Spike, Bramble, Thistle, Conker, Prickles) |
