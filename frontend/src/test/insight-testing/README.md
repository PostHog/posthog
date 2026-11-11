# Insight testing

A test wrapper for rendering insight components (or any component that depends on insight infrastructure) with mocked data and a chart inspection API.

## Quick start

```tsx
import { buildTrendsQuery, chart, getChart, renderInsight } from '~/test/insight-testing'

renderInsight({
  query: buildTrendsQuery({
    series: [{ kind: NodeKind.EventsNode, event: '$pageview', name: '$pageview' }],
  }),
})

const tooltip = await chart.hoverTooltip(2)
expect(tooltip.row('Pageview')).toContain('134')
expect(getChart().seriesCount).toBe(1)
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

`getChart()` comes from `@posthog/quill-charts/testing`.
It reads the rendered chart through its stable DOM hooks: series count, axis ticks and titles, legend, reference lines and value labels.
`annotationBadges()` reads the PostHog annotation badges on the chart.
See the [quill-charts testing guide](../../../../packages/quill/packages/charts/src/docs/TESTING.md).

`chart` wraps the gestures for insight charts, which render the InsightTooltip table:

| API                        | Description                                         |
| -------------------------- | --------------------------------------------------- |
| `chart.hoverTooltip(i)`    | Hover the point at index `i` and return the tooltip |
| `chart.clickAtIndex(i)`    | Hover, then click the point at index `i`            |
| `chart.clickTooltipRow(l)` | Click the row labelled `l` in a pinned tooltip      |
| `chart.getTooltip()`       | The current tooltip element, or `null`              |

`sqlChart` does the same for SQL charts, which render the quill `DefaultTooltip`.

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

After any interaction, wrap the assertions in `waitFor`.

## Test data

Canned data lives in `test-data.ts`. The mock query handler automatically resolves
queries to the right data based on event name and breakdown property.

| Series                             | Data                                                 |
| ---------------------------------- | ---------------------------------------------------- |
| `$pageview`                        | `[45, 82, 134, 210, 95]` over Mon–Fri                |
| `Napped`                           | `[1, 3, 5, 8, 2]` over Mon–Fri                       |
| `Napped` + breakdown by `hedgehog` | 5 series (Spike, Bramble, Thistle, Conker, Prickles) |
