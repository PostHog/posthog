# Testing hog-charts

Render a chart, drive interactions through the `chart` accessor, assert against a structured tooltip snapshot or the chart's DOM. Pure logic is tested at the `core/` layer, never against the canvas.

## TL;DR

```tsx
import { renderHogChart } from 'lib/hog-charts/testing'

it('shows the hovered series in the tooltip', async () => {
  const { chart } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)
  chart.hoverAtIndex(1)
  const tooltip = await chart.waitForTooltip()
  expect(tooltip.label).toBe('Tue')
  expect(tooltip.seriesData).toHaveLength(SERIES.length)
})
```

That's the whole shape: render → hover → snapshot → assert. No `beforeEach`, no `cleanup()`, no DOM-level glue.

## What `renderHogChart` does

- Calls `render(ui)` from `@testing-library/react`.
- Auto-installs the jsdom mocks (`ResizeObserver`, `getBoundingClientRect`) and a synchronous `requestAnimationFrame` shim. Idempotent — only happens once per test run.
- Calls `cleanup()` and removes any tooltip portal left behind by a previous test (RTL's auto-cleanup doesn't always reach `FloatingPortal` children).
- Intercepts the (optional) `tooltip` render prop via `cloneElement` so `chart.waitForTooltip()` can return the structured `TooltipContext` the chart computed. If the consumer didn't pass a tooltip we fall through to `DefaultTooltip` — same as the chart's natural default. If they did, we wrap and call through unchanged.
- Reads `ui.props.labels.length` and caches it on the accessor so `chart.hoverAtIndex(i)` doesn't need a `totalLabels` argument.
- Returns the standard `RenderResult` with a `chart` accessor attached.

## The `chart` accessor

`chart` is the **single surface** for chart-level tests. Reads come from the DOM; interactions fire real events; the tooltip snapshot includes the structured `TooltipContext` the chart computed.

```tsx
chart.element // wrapper div
chart.seriesCount // visible series count, from the canvas's aria-label
chart.yTicks() // ['0', '20', '40', …]
chart.yRightTicks() // right-axis ticks (multi-axis charts)
chart.xTicks() // post-collision-avoidance x ticks
chart.hasRightAxis // boolean
chart.referenceLines() // [{ label, position, color, orientation }, …]
chart.valueLabels() // [{ text, color }, …]
chart.anomalyPoints() // [{ element, color }, …]  (TimeSeriesLineChart)
chart.annotationBadges() // HTMLElement[]

chart.hoverAtIndex(i) // mouseMove over labels[i]; uses the cached label count
await chart.clickAtIndex(i) // hover-then-click; resolves after the click handler runs
const tooltip = await chart.waitForTooltip()
```

### The tooltip snapshot

`chart.waitForTooltip()` returns once the tooltip portal mounts:

```tsx
const tooltip = await chart.waitForTooltip()

tooltip.label // 'Tue'
tooltip.dataIndex // 1
tooltip.seriesData // [{ series, value, color }, …] — same structure the chart's tooltip prop receives
tooltip.position // { x, y } in canvas pixels
tooltip.hoverPosition // cursor coords when known, else null
tooltip.element // the rendered portal element — for DOM assertions
tooltip.isPinned // true when the user has pinned via click
```

Prefer the structured fields. Reach for `tooltip.element` when you need to assert on the rendered tooltip's text or a custom render prop's output.

## Custom render functions / external usage

`getHogChart(scope)` works on **any** rendered tree for **DOM-rendered** properties — axis ticks, value labels, reference lines, annotation badges, the canvas wrapper, the rendered tooltip element:

```tsx
import { render, fireEvent } from '@testing-library/react'
import { ensureJsdom, getHogChart, waitForHogChartTooltip } from 'lib/hog-charts/testing'

ensureJsdom()

it('renders a chart somewhere deep in the dashboard', async () => {
  const { container } = render(<Dashboard />)
  const chart = getHogChart(container)
  expect(chart.referenceLines()).toHaveLength(1)
  expect(chart.yTicks()).toContain('0')

  fireEvent.mouseMove(chart.element, { clientX: 200, clientY: 200 })
  const tooltipEl = await waitForHogChartTooltip()
  expect(tooltipEl.textContent).toContain('Tue')
})
```

What you **don't** get from `getHogChart(scope)` directly:

- `chart.hoverAtIndex(i)` / `chart.clickAtIndex(i)` — they need the label count, which `renderHogChart` reads off the chart's props. With a custom render, fire mouse events directly or use the module-level `hoverAtIndex(wrapper, i, totalLabels)`.
- `chart.waitForTooltip()` returning a structured `TooltipSnapshot` — the tooltip-prop interception lives in `renderHogChart`. Use the module-level `waitForHogChartTooltip()` for the element. If you also need the structured `TooltipContext`, render the chart at the top level via `renderHogChart` instead.

The full structured experience requires `renderHogChart`; everything DOM-shaped works with a plain `render`.

## Recipes

### Pin the tooltip on click

```tsx
it('pins on click when pinnable', async () => {
  const { chart } = renderHogChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} config={{ tooltip: { pinnable: true } }} />
  )
  await chart.clickAtIndex(1)
  const tooltip = await chart.waitForTooltip()
  expect(tooltip.isPinned).toBe(true)
})
```

### Custom tooltip render prop

When the consumer passes `tooltip`, the chart calls it with the (possibly narrowed) `TooltipContext`. The same context is on `tooltip.seriesData` etc. — usually you can assert against the snapshot directly without round-tripping through DOM:

```tsx
it('passes hovered seriesData to the tooltip prop', async () => {
  const { chart } = renderHogChart(<LineChart series={SERIES} labels={LABELS} theme={THEME} />)
  chart.hoverAtIndex(1)
  const tooltip = await chart.waitForTooltip()
  expect(tooltip.seriesData).toHaveLength(SERIES.length)
})
```

Reach for `tooltip.element.textContent` when the test specifically asserts what the user sees rendered.

### Click a data point

```tsx
it('invokes onPointClick', async () => {
  const onPointClick = jest.fn()
  const { chart } = renderHogChart(
    <LineChart series={SERIES} labels={LABELS} theme={THEME} onPointClick={onPointClick} />
  )
  await chart.clickAtIndex(1)
  expect(onPointClick).toHaveBeenCalledWith(expect.objectContaining({ dataIndex: 1, label: 'Tue' }))
})
```

### Reference lines and value labels

```tsx
const { chart } = renderHogChart(
  <LineChart series={SERIES} labels={LABELS} theme={THEME}>
    <ReferenceLine value={15} label="Target" />
  </LineChart>
)
expect(chart.referenceLines()).toEqual([expect.objectContaining({ label: 'Target', orientation: 'horizontal' })])
```

### Render error captured by ChartErrorBoundary

```tsx
it('reports render errors through onError', async () => {
  const onError = jest.fn()
  const tooltip = (): React.ReactNode => {
    throw new Error('boom')
  }
  const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
  try {
    const { chart } = renderHogChart(
      <LineChart series={SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} onError={onError} />
    )
    chart.hoverAtIndex(1)
    await waitFor(() => expect(onError).toHaveBeenCalled())
  } finally {
    consoleErrorSpy.mockRestore()
  }
})
```

## Pure unit tests (`core/`)

Geometry, scales, interactions, and canvas drawing live as pure functions in `core/` and are tested directly. No `renderHogChart`. Mock the canvas only when asserting on draw calls — and prefer asserting on the structured output of helpers (e.g. `computeSeriesBars`) over snooping on `ctx.moveTo.mock.calls`.

When a test does need a canvas mock, sample one representative call rather than asserting on every call in a loop. `drawGrid` emits the same shape per tick, so testing one tick is enough; for-loops over `mock.calls` invite branching logic in tests, which we avoid.

## Anti-patterns

**Don't mock `core/canvas-renderer`.** Reaching into draw-function call lists tests an internal contract through a side channel. Test the geometry directly in `core/`:

```tsx
// wrong
jest.mock('../core/canvas-renderer', () => ({ ...jest.requireActual('../core/canvas-renderer'), drawBars: jest.fn() }))
expect((drawBars as jest.Mock).mock.calls[0][2][0].corners.topLeft).toBe(true)
```

**Don't read `scales._private`.** Opaque chart-type-private slot. Anything reachable through it is reachable more cleanly at the chart type's pure-scale layer.

**Don't inspect canvas pixels.** JSdom's canvas is a stub — no `getContext('2d')` spies, no pixel snapshots.

**Don't write `it.each` matrices that only assert "a canvas rendered".** Each row should read at least one observable property of that permutation.

**Don't reach into React internals.** `useRef` values, internal effects, and d3 scale objects are not test surface. The accessor and tooltip snapshot are.

**Don't add boilerplate that's now automatic.** `setupJsdom()` / `setupSyncRaf()` / `cleanup()` in `beforeEach` / `afterEach` are no longer needed — `renderHogChart` handles all three. Use the explicit functions only when you need fine-grained teardown control (rare).

## Module reference

```ts
import {
  renderHogChart, // render + chart accessor (full structured tooltip + hover/click)
  getHogChart, // accessor over an already-rendered tree (DOM-only by default)
  ensureJsdom, // explicit one-time jsdom setup; renderHogChart calls this
  setupJsdom, // returns teardown — for tests with fine-grained mock control
  setupSyncRaf, // returns teardown — for fine-grained RAF control
  dimensions,
  mockRect, // jsdom mock dimensions in CSS pixels
  makeSeries, // small `Series` fixture builder

  // Module-level interaction/tooltip helpers — used outside renderHogChart's scope
  hoverAtIndex, // hoverAtIndex(wrapper, i, totalLabels)
  clickAtIndex, // clickAtIndex(wrapper, i, totalLabels)
  waitForHogChartTooltip, // resolves to the portal element
  getHogChartTooltip, // sync read; null if not mounted
  HOG_CHARTS_TOOLTIP_SELECTOR, // for custom queries
} from 'lib/hog-charts/testing'

import type {
  HogChart, // accessor type (generic on series Meta)
  GetHogChartOptions, // options for getHogChart (capture closure, totalLabels)
  TooltipSnapshot, // chart.waitForTooltip() return type
  HogChartTooltip, // raw tooltip handle (element + isPinned)
} from 'lib/hog-charts/testing'
```
