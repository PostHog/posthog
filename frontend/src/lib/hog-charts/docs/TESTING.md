# Testing

Two audiences:

- **Embedding hog-charts** in your own component or page and writing tests
  for that surrounding code → [Testing code that uses hog-charts](#testing-code-that-uses-hog-charts).
- **Working on the library itself** — chart types, overlays, the draw
  loop → [Testing the library itself](#testing-the-library-itself).

The contract both sections rely on: the `data-attr` selectors and the
`HogChart` accessor are stable. Renaming a `data-attr` is a breaking
change — it breaks consumers' tests as much as renaming an exported type.
JSdom's canvas is a stub, so canvas pixels aren't a viable test surface
anyway — assertions go through the DOM.

## Testing code that uses hog-charts

You've rendered a tree that contains a chart somewhere — a dashboard, an
insight scene, a custom panel. Use your own `render` (or RTL wrappers like
kea-test-utils) and read the chart with `getHogChart(scope)`:

```tsx
import { render } from '@testing-library/react'
import { ensureJsdom, getHogChart, hoverAtIndex, waitForHogChartTooltip } from 'lib/hog-charts/testing'

ensureJsdom()

it('renders the goal line on the dashboard chart', async () => {
  const { container } = render(<Dashboard />)
  const chart = getHogChart(container)

  expect(chart.referenceLines()).toHaveLength(1)
  expect(chart.yTicks()).toContain('0')

  hoverAtIndex(chart.element, 1, LABELS.length)
  const tooltip = await waitForHogChartTooltip()
  expect(tooltip.textContent).toContain('Tue')
})
```

`ensureJsdom()` installs the jsdom mocks (`ResizeObserver`,
`getBoundingClientRect`) and a synchronous `requestAnimationFrame` shim.
It's idempotent — call it once at the top of a file and forget about it.

The accessor surface (full list in `testing/accessor.ts`):

```ts
chart.element // wrapper div for the chart
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
chart.annotationBadges() // HTMLElement[]
```

For interactions, use the module-level helpers:

- `hoverAtIndex(wrapper, i, totalLabels)` — `mouseMove` over labels[i].
- `clickAtIndex(wrapper, i, totalLabels)` — hover-then-click. Resolves
  after the click handler runs.
- `waitForHogChartTooltip()` — resolves with the rendered tooltip element
  once it mounts in the `FloatingPortal`.

`chart.hoverAtIndex(i)` and `chart.waitForTooltip()` (returning a
structured `TooltipSnapshot` with `seriesData`, `isPinned`, etc.) need
`renderHogChart` — they read label count and the captured `TooltipContext`
that only the library's own render wrapper sets up. For most consumer
tests, DOM assertions through the accessor are enough.

## Testing the library itself

Chart-level tests live under `charts/<name>/<Name>.test.tsx` and overlay
tests under `overlays/<Name>.test.tsx`. They render the chart at the top
level via `renderHogChart` and assert through the `chart` accessor.

```tsx
import type { ChartTheme, Series } from '../core/types'
import { renderHogChart } from '../testing'
import { LineChart } from './LineChart'

const THEME: ChartTheme = { colors: ['#111', '#222'], backgroundColor: '#ffffff' }
const LABELS = ['Mon', 'Tue', 'Wed']
const SERIES: Series[] = [{ key: 'a', label: 'A', data: [1, 2, 3] }]

describe('LineChart', () => {
  it('formats percent-stack y-ticks by default', () => {
    const { chart } = renderHogChart(
      <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ percentStackView: true }} />
    )
    expect(chart.yTicks().some((t) => t.endsWith('%'))).toBe(true)
  })
})
```

`renderHogChart` is `render` plus three things consumers don't need:
auto-`ensureJsdom`, tooltip-context capture (so `chart.waitForTooltip()`
returns the structured `TooltipContext`), and a cached `labels.length`
(so `chart.hoverAtIndex(i)` doesn't take a `totalLabels` argument).

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

Prefer the structured fields. Reach for `tooltip.element.textContent` only
when the test specifically asserts what the user sees rendered.

### Recipes

#### Pin a tooltip on click

```tsx
it('pins the tooltip on click when pinnable', async () => {
  const { chart } = renderHogChart(
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
  const { chart } = renderHogChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} onPointClick={onPointClick} />
  )

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
  const { chart } = renderHogChart(<LineChart series={series} labels={LABELS} theme={THEME} />)

  expect(chart.hasRightAxis).toBe(true)
  expect(chart.yRightTicks().length).toBeGreaterThan(0)
})
```

#### Catch a render error

Each chart wraps its inner tree in `ChartErrorBoundary`, which surfaces
render errors through `onError` instead of unmounting the parent. The
simplest forcing function is a `tooltip` render prop that throws, since
the boundary covers tooltip rendering during hover.

```tsx
it('reports render errors through onError', () => {
  const onError = jest.fn()
  const tooltip = (): React.ReactNode => {
    throw new Error('boom')
  }
  const { chart } = renderHogChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} onError={onError} />
  )

  chart.hoverAtIndex(1)
  expect(onError).toHaveBeenCalled()
})
```

### Anti-patterns

**Don't mock `core/canvas-renderer`.** Reaching into draw-function call
lists tests an internal contract through a side channel. The geometry
that produced those calls lives in `core/bar-layout.ts` — test it
directly in `core/bar-layout.test.ts` against `computeSeriesBars`.

**Don't read `scales._private`.** It's an opaque chart-type-private slot.
Anything reachable through it is reachable more cleanly at the chart
type's pure-scale layer.

**Don't inspect canvas pixels.** No `getContext('2d')` spies, no pixel
snapshots — JSdom's canvas is a stub anyway.

**Don't fall back to `container.querySelector('canvas')` for canvas
presence.** `renderHogChart` already throws when the canvas is missing.

**Don't write `it.each` matrices that only assert "a canvas rendered".**
Each row should read at least one observable property of that
permutation — `chart.yTicks().some(t => t.endsWith('%'))` for percent
layout, `chart.hasRightAxis` for a multi-axis case.

**Don't reach into React internals.** `useRef` values, internal effects,
and d3 scale objects are not test surface. The accessor and tooltip
helpers are the entire surface.
