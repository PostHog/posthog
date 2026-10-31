# Testing

Two audiences:

- **Embedding a chart** in your own component or page and writing tests for that surrounding code → [Testing code that uses charts](#testing-code-that-uses-charts).
- **Working on the library itself** — chart types, overlays, the draw loop → [Testing the library itself](#testing-the-library-itself).

The contract both sections rely on: the `data-attr` selectors and the `ChartAccessor` are stable. Renaming a `data-attr` is a breaking change — it breaks consumers' tests as much as renaming an exported type. JSdom's canvas is a stub, so canvas pixels aren't a viable test surface anyway — assertions go through the DOM.

## Testing code that uses charts

You've rendered a tree that contains a chart somewhere: a dashboard, an insight scene, a custom panel. Render it your usual way, then read the chart with `findChart()`:

```tsx
import { render } from '@testing-library/react'
import { findChart, setupChartTests } from '@posthog/quill-charts/testing'

setupChartTests()

it('renders the goal line on the dashboard chart', async () => {
  render(<Dashboard />)
  const chart = await findChart()

  expect(chart.referenceLines()).toHaveLength(1)

  const tooltip = await chart.hoverTooltip(1)
  expect(tooltip.label()).toBe('Tue')
  expect(tooltip.value('Pageviews')).toBe('134')
})
```

- Outside this repo, install `@testing-library/react` next to `@posthog/quill-charts`. The helpers need a jsdom test environment and a runner with global `beforeEach` and `afterEach`.
- `setupChartTests()` registers the hooks every chart test needs: jsdom mocks for `ResizeObserver` and `getBoundingClientRect`, synchronous animation frames, and cleanup after each test.
- `findChart()` waits for the chart to render. Pass `seriesCount` to wait for a specific series count, or `scope` when the page has more than one chart. `getChart()` is the synchronous version.
- `chart.hoverTooltip(i)` hovers the label at index `i` until the tooltip shows its content, then reads it as a `DefaultTooltip`. `tooltip.clickRow('Pageviews')` clicks a row. For a custom tooltip, read `tooltip.element`.

The accessor surface (full list in `testing/accessor.ts`):

```ts
chart.element // wrapper div for the chart
chart.canvas // the static (data) canvas, not the aria-hidden hover overlay
chart.seriesCount // visible series count, from the canvas's aria-label
chart.yTicks() // ['0', '20', '40', …]
chart.yRightTicks() // right-axis ticks (multi-axis charts)
chart.xTicks() // post-collision-avoidance x ticks
chart.xAxisLabel() // optional x-axis label
chart.yAxisLabel() // optional y-axis label
chart.xAxisLabelElement() // optional x-axis label SVG element
chart.yAxisLabelElement() // optional y-axis label SVG element
chart.hasRightAxis // boolean
chart.referenceLines() // [{ label, position, color, orientation }, …]
chart.valueLabels() // [{ text, color }, …]
chart.anomalyPoints() // [{ element, color }, …] (TimeSeriesLineChart)
chart.legend() // legend container in the render scope, null when hidden
chart.legendItems() // [{ label, secondaryLabel }, …] legend rows in the render scope, empty when hidden
chart.clickLegendItem('A', { additive: true }) // click a legend row, additive toggles instead of isolating
chart.slope.valueLabels() // [{ text, color, side }, …] slope value labels, start and end columns
chart.slope.seriesLabels() // slope series names, after collision avoidance
chart.sankey.nodeLabels() // ['/home', '/pricing', …] Sankey node labels in layout order, after overlap hiding
chart.sankey.columnLabels() // ['Step 1', 'Step 2', …] Sankey column headers, left to right
chart.pie.sliceLabels() // [{ text, lines }, …] on-slice labels, one entry per slice
```

Gestures work under any wrapper, because the chart records its label count on its root:

- `chart.hoverAtIndex(i)` fires one `mouseMove` over the label at index `i`, without waiting.
- `await chart.clickAtIndex(i)` hovers, then clicks. It resolves after the click handler runs.
- `chart.dragSelection(from, to)` drags between two label indices, for drag-to-zoom.

`chart.waitForTooltip()` returns the structured `TooltipContext` (`seriesData`, `isPinned` and so on). It needs `renderChart`, which captures that context.

## Testing the library itself

Chart-level tests live under `charts/<name>/<Name>.test.tsx` and overlay tests under `overlays/<Name>.test.tsx`. They render the chart at the top level via `renderChart` and assert through the `chart` accessor.

```tsx
import type { ChartTheme, Series } from '../core/types'
import { renderChart } from '../testing'
import { LineChart } from './LineChart'

const THEME: ChartTheme = { colors: ['#111', '#222'], backgroundColor: '#ffffff' }
const LABELS = ['Mon', 'Tue', 'Wed']
const SERIES: Series[] = [{ key: 'a', label: 'A', data: [1, 2, 3] }]

describe('LineChart', () => {
  it('formats percent-stack y-ticks by default', () => {
    const { chart } = renderChart(
      <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ percentStackView: true }} />
    )
    expect(chart.yTicks().some((t) => t.endsWith('%'))).toBe(true)
  })
})
```

`renderChart` is `render` plus the jsdom mocks and tooltip-context capture, so `chart.waitForTooltip()` returns the context the chart's tooltip content received.

### Interactions and tooltip context

```tsx
chart.hoverAtIndex(1)
await chart.clickAtIndex(1)

const tooltip = await chart.waitForTooltip()
tooltip.label // 'Tue'
tooltip.dataIndex // 1
tooltip.seriesData // [{ series, value, color }, …] — same shape the tooltip render prop receives
tooltip.element // rendered portal element
tooltip.isPinned // true once the user has pinned via click
```

Prefer the structured fields. Reach for `tooltip.element.textContent` only when the test specifically asserts what the user sees rendered.

### Recipes

#### Pin a tooltip on click

```tsx
it('pins the tooltip on click when pinnable', async () => {
  const { chart } = renderChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ tooltip: { pinnable: true } }} />
  )

  await chart.clickAtIndex(1)
  const tooltip = await chart.waitForTooltip()
  expect(tooltip.isPinned).toBe(true)
})
```

#### Click a data point

```tsx
it('invokes onPointClick with the clicked column', async () => {
  const onPointClick = jest.fn()
  const { chart } = renderChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} onPointClick={onPointClick} />)

  await chart.clickAtIndex(1)
  expect(onPointClick).toHaveBeenCalledWith(expect.objectContaining({ dataIndex: 1, label: 'Tue', value: 2 }))
})
```

#### Render a second y-axis

```tsx
it('renders a right axis when a series opts in', () => {
  const series: Series[] = [
    { key: 'a', label: 'A', data: [10, 20, 30] },
    { key: 'b', label: 'B', data: [1000, 2000, 3000], yAxisId: 'right' },
  ]
  const { chart } = renderChart(<LineChart series={series} labels={LABELS} theme={THEME} />)

  expect(chart.hasRightAxis).toBe(true)
  expect(chart.yRightTicks().length).toBeGreaterThan(0)
})
```

#### Catch a render error

Each chart wraps its inner tree in `ChartErrorBoundary`, which surfaces render errors through `onError` instead of unmounting the parent. The simplest forcing function is a `tooltip` render prop that throws, since the boundary covers tooltip rendering during hover.

```tsx
it('reports render errors through onError', () => {
  const onError = jest.fn()
  const tooltip = (): React.ReactNode => {
    throw new Error('boom')
  }
  const { chart } = renderChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} onError={onError} />
  )

  chart.hoverAtIndex(1)
  expect(onError).toHaveBeenCalled()
})
```

### Anti-patterns

**Don't mock `core/canvas-renderer`.** Reaching into draw-function call lists tests an internal contract through a side channel. The geometry that produced those calls lives in `core/bar-layout.ts` — test it directly in `core/bar-layout.test.ts` against `computeSeriesBars`.

**Don't read `scales._private`.** It's an opaque chart-type-private slot. Anything reachable through it is reachable more cleanly at the chart type's pure-scale layer.

**Don't inspect canvas pixels.** No `getContext('2d')` spies, no pixel snapshots — JSdom's canvas is a stub anyway.

**Don't fall back to `container.querySelector('canvas')` for canvas presence.** `renderChart` already throws when the canvas is missing. To act on a rendered canvas — asserting its backing store, dispatching a canvas-level event like `contextrestored` — use `chart.canvas` rather than re-querying the DOM. Absence assertions (`expect(container.querySelector('canvas')).toBeNull()`) still need a raw query, since the accessor throws when there's no canvas.

**Don't write `it.each` matrices that only assert "a canvas rendered".** Each row should read at least one observable property of that permutation — `chart.yTicks().some(t => t.endsWith('%'))` for percent layout, `chart.hasRightAxis` for a multi-axis case.

**Don't reach into React internals.** `useRef` values, internal effects, and d3 scale objects are not test surface. The accessor and tooltip helpers are the entire surface.
