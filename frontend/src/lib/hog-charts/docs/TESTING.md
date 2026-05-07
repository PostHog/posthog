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
chart.hoverAtIndex(1) // mouseMove over labels[1]
await chart.clickAtIndex(1) // hover then click
```

The label count comes from `ui.props.labels`, captured at `renderHogChart` time. Outside `renderHogChart` (e.g. when calling `getHogChart(scope)` on a custom render tree), use the module-level `hoverAtIndex(wrapper, i, totalLabels)` / `clickAtIndex(wrapper, i, totalLabels)` instead.

### Tooltip helpers

`chart.waitForTooltip()` resolves once the tooltip mounts and returns a snapshot — the structured `TooltipContext` the chart computed plus the rendered portal element and an `isPinned` flag.

```tsx
const tooltip = await chart.waitForTooltip()
expect(tooltip.label).toBe('Tue')
expect(tooltip.seriesData).toHaveLength(2)
expect(tooltip.element.textContent).toContain('Tue')
expect(tooltip.isPinned).toBe(false)
```

The tooltip mounts in a `FloatingPortal` on the document root, so it isn't inside `chart.element`. Module-level `waitForHogChartTooltip()` / `getHogChartTooltip()` are still exported for cases where you don't have a `chart` accessor handy (e.g. an insight tree behind kea wrappers — see `frontend/src/test/insight-testing/`).

## Boilerplate

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

`renderHogChart` installs the jsdom mocks (`ResizeObserver`, `getBoundingClientRect`) and a synchronous `requestAnimationFrame` shim on first call — without them the chart sees 0×0 and the static-layer draw doesn't flush before assertions. It also calls `cleanup()` and removes any leftover tooltip portal, so test files don't need a `beforeEach`/`afterEach` for those. Use the explicit `setupJsdom()` / `setupSyncRaf()` only when you need fine-grained teardown control.

## Recipes

### Hover and pin a tooltip

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

### Assert against the structured tooltip context

The `chart.waitForTooltip()` snapshot includes the same `TooltipContext` the chart's `tooltip` render prop would receive — read `seriesData`, `label`, `dataIndex`, etc. directly without round-tripping through DOM.

```tsx
it('passes hovered seriesData to the tooltip', async () => {
  const { chart } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)

  chart.hoverAtIndex(1)
  const tooltip = await chart.waitForTooltip()
  expect(tooltip.seriesData.map((s) => s.value)).toEqual([2])
})
```

When the test cares about what the user actually sees rendered, reach for `tooltip.element.textContent`.

### Click a data point

Use `chart.clickAtIndex` to fire a click on a specific column and assert that the chart's `onPointClick` callback received the expected `PointClickData` (`seriesIndex`, `dataIndex`, `series`, `value`, `label`, `crossSeriesData`). It resolves after the click handler runs.

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

  chart.hoverAtIndex(1)
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
