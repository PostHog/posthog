# Testing

Render a chart, read the DOM through the `chart` accessor, drive interactions through `hoverAtIndex` / `clickAtIndex` and the tooltip helpers. Never reach into the canvas or `scales._private`. Pure logic is tested at the `core/` layer, not at the chart level.

This file documents the conventions encoded in the `testing/` module. They apply to chart-level tests under `charts/` and to overlay tests under `overlays/`.

## The DOM is the testing contract

`data-attr` selectors and the `HogChart` accessor are the stable surface chart-level tests assert against. Renaming a `data-attr` is a breaking change — it breaks consumers' tests as much as renaming an exported type. JSdom's canvas is a stub (`getContext('2d')` returns a no-op context), so canvas pixels aren't a viable test surface anyway — assertions go through the DOM.

## Testing module API

### `renderHogChart`

Wraps `@testing-library/react`'s `render` and attaches a `chart` accessor. Throws if no hog-charts canvas mounted — use plain `render` for non-chart components.

```tsx
const { chart, container } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)
expect(chart.seriesCount).toBe(SERIES.length)
```

### The `HogChart` accessor

Reads what the chart rendered without poking at internals or canvas pixels. Helpers below take a `wrapper` argument — that's `chart.element`.

```tsx
const { chart } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)

chart.element // wrapper div for this chart
chart.seriesCount // number of non-excluded series rendered
chart.yTicks() // ['0', '10', '20', …]
chart.yRightTicks() // right-axis ticks for multi-axis charts
chart.xTicks() // post-collision-avoidance x ticks
chart.hasRightAxis // boolean

chart.referenceLines() // [{ label: 'Target', position: 142, color: 'rgb(...)', orientation: 'horizontal' }, …]
chart.valueLabels() // [{ text: '50%', color: 'rgb(...)' }, …]
chart.annotationBadges() // HTMLElement[]
```

### Interaction helpers

Map a label index to canvas coordinates and fire the right event. `clickAtIndex` is hover-then-click — the chart's click handler reads live tooltip context to choose between pinning and `onPointClick`, so a bare `fireEvent.click` without a prior hover takes the wrong branch.

```tsx
hoverAtIndex(chart.element, 1, LABELS.length) // mouseMove over labels[1]
await clickAtIndex(chart.element, 1, LABELS.length) // hover then click
```

### Tooltip helpers

The tooltip mounts in a `FloatingPortal` on the document root, so it isn't inside the chart wrapper and can't be reached with `chart.element.querySelector`.

```tsx
const tooltip = await waitForHogChartTooltip() // resolves once mounted
expect(tooltip.textContent).toContain('Tue')

const current = getHogChartTooltip() // null if not mounted
expect(current?.classList.contains('hog-charts-tooltip--pinned')).toBe(true)
```

## Boilerplate

```tsx
import { cleanup } from '@testing-library/react'

import type { ChartTheme, Series } from '../core/types'
import { renderHogChart, setupJsdom, setupSyncRaf } from '../testing'
import { LineChart } from './LineChart'

const THEME: ChartTheme = { colors: ['#111', '#222'], backgroundColor: '#ffffff' }
const LABELS = ['Mon', 'Tue', 'Wed']
const SERIES: Series[] = [{ key: 'a', label: 'A', data: [1, 2, 3] }]

describe('LineChart', () => {
  let teardownJsdom: () => void
  let teardownRaf: () => void

  beforeEach(() => {
    teardownJsdom = setupJsdom()
    teardownRaf = setupSyncRaf()
  })
  afterEach(() => {
    teardownRaf()
    teardownJsdom()
    cleanup()
  })

  it('formats percent-stack y-ticks by default', () => {
    const { chart } = renderHogChart(
      <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ percentStackView: true }} />
    )
    expect(chart.yTicks().some((t) => t.endsWith('%'))).toBe(true)
  })
})
```

`setupJsdom` mocks `ResizeObserver` and `getBoundingClientRect` so the chart computes real dimensions — without it the chart sees 0×0 and renders nothing measurable. `setupSyncRaf` runs `requestAnimationFrame` synchronously so the static-layer draw commits to the DOM before assertions run; without it the accessor reads stale state and `yTicks()` / `valueLabels()` come back empty.

## Recipes

### Hover and pin a tooltip

```tsx
it('pins the tooltip on click when pinnable', async () => {
  const { chart } = renderHogChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ tooltip: { pinnable: true } }} />
  )

  hoverAtIndex(chart.element, 1, LABELS.length)
  const tooltip = await waitForHogChartTooltip()
  expect(tooltip.textContent).toContain('Tue')

  await clickAtIndex(chart.element, 1, LABELS.length)
  expect(getHogChartTooltip()?.classList.contains('hog-charts-tooltip--pinned')).toBe(true)
})
```

### Render a custom tooltip

When a chart is given a `tooltip` render prop, that function receives `TooltipContext`. Trigger it with `hoverAtIndex` and read the rendered output through the tooltip portal.

```tsx
it('passes hovered seriesData to a custom tooltip', async () => {
  const tooltip = (ctx: TooltipContext): React.ReactNode => (
    <div data-attr="custom-tooltip">{ctx.seriesData.map((s) => s.value).join(',')}</div>
  )
  const { chart } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} />)

  hoverAtIndex(chart.element, 1, LABELS.length)
  const node = await waitForHogChartTooltip()
  expect(node.querySelector('[data-attr="custom-tooltip"]')?.textContent).toBe('2')
})
```

### Click a data point

Use `clickAtIndex` to fire a click on a specific column and assert that the chart's `onPointClick` callback received the expected `PointClickData` (`seriesIndex`, `dataIndex`, `series`, `value`, `label`, `crossSeriesData`). `clickAtIndex` resolves after the click handler runs.

```tsx
it('invokes onPointClick with the clicked column', async () => {
  const onPointClick = jest.fn()
  const { chart } = renderHogChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} onPointClick={onPointClick} />
  )

  await clickAtIndex(chart.element, 1, LABELS.length)
  expect(onPointClick).toHaveBeenCalledWith(expect.objectContaining({ dataIndex: 1, label: 'Tue', value: 2 }))
})
```

### Render a second y-axis

When a series declares `yAxisId: 'right'`, the chart renders a right-side y-axis. Assert through the accessor's `hasRightAxis` and `yRightTicks()`.

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

### Catch a render error

Each chart wraps its inner tree in `ChartErrorBoundary`, which surfaces render errors through the `onError` prop instead of unmounting the parent. To trigger one, force a throw during render — the simplest forcing function is a `tooltip` render prop that throws, since the boundary covers tooltip rendering during hover.

```tsx
it('reports render errors through onError', () => {
  const onError = jest.fn()
  const tooltip = (): React.ReactNode => {
    throw new Error('boom')
  }
  const { chart } = renderHogChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} onError={onError} />
  )

  hoverAtIndex(chart.element, 1, LABELS.length)
  expect(onError).toHaveBeenCalled()
})
```

## Anti-patterns

**Don't mock `core/canvas-renderer`.** Reaching into draw-function call lists tests an internal contract through a side channel:

```tsx
// wrong
jest.mock('../core/canvas-renderer', () => ({ ...jest.requireActual('../core/canvas-renderer'), drawBars: jest.fn() }))
expect((drawBars as jest.Mock).mock.calls[0][2][0].corners.topLeft).toBe(true)
```

The geometry that produced those calls lives in `core/bar-layout.ts` — test it directly in `core/bar-layout.test.ts` against `computeSeriesBars`.

**Don't read `scales._private`.** It's an opaque chart-type-private slot. Anything reachable through it is reachable more cleanly at the chart type's pure-scale layer.

**Don't inspect canvas pixels.** No `getContext('2d')` spies, no pixel snapshots — JSdom's canvas is a stub anyway.

**Don't fall back to `container.querySelector('canvas')` for canvas presence.** `renderHogChart` already throws when the canvas is missing.

**Don't write `it.each` matrices that only assert "a canvas rendered".** Each row should read at least one observable property of that permutation — `chart.yTicks().some(t => t.endsWith('%'))` for a percent layout, `chart.hasRightAxis` for a multi-axis case.

**Don't reach into React internals.** `useRef` values, internal effects, and d3 scale objects are not test surface. The accessor and tooltip helpers are the entire surface.
