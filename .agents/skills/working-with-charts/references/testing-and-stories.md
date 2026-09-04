# Testing and stories

The library's [TESTING.md](../../../../packages/quill/packages/charts/src/docs/TESTING.md) is the contract.
This file is the app-side layer on top of it.

## Three test layers

Keep them separate.
A test that renders a chart to assert series content, or asserts raw series from inside a rendered scene, is in the wrong layer.

| Layer          | File                                                 | Renders   | Asserts on                                                                                       |
| -------------- | ---------------------------------------------------- | --------- | ------------------------------------------------------------------------------------------------ |
| Pure transform | `*Transforms.test.ts` next to the transform          | Nothing   | The `Series[]`, `labels`, config, and meta the transform returns                                 |
| Adapter        | `<ChartComponent>.test.tsx` next to the component    | The scene | What the user sees: ticks, tooltip rows, reference lines, legend rows, the persons modal opening |
| Library        | `packages/quill/packages/charts/src/**/*.test.ts(x)` | The chart | Geometry under `core/`, DOM through the `HogChart` accessor for charts and overlays              |

Most app changes need the first two.
Touch the third only when you changed the library.

## Pure transform tests

Call the transform with hand-built results and assert on the output shape.
Cover the branches the transform adds: hidden series, compare-to-previous, percent layout, the in-progress tail, multi-axis assignment.

```ts
it('dashes the in-progress tail of the current period only', () => {
  const series = buildTrendsSeries(results, { incompletenessOffsetFromEnd: -1, getColor: () => '#000' })
  expect(series[0].stroke?.partial?.fromIndex).toBe(results[0].data.length - 1)
  expect(series[1].stroke).toBeUndefined()
})
```

## Adapter tests

Render the real scene and read the chart through the DOM.

- Insight charts: `renderInsight` from `~/test/insight-testing`, then the `chart`, `legend`, `display`, `compare`, `breakdown`, and `personsModal` interaction helpers from the same module. `chart.hoverTooltip(index)` returns an accessor with `row(label)`, `header()`, and friends.
- Any other chart: your own `render`, then `getHogChart(container)` from `@posthog/quill-charts/testing` for `yTicks()`, `xTicks()`, `referenceLines()`, `valueLabels()`, `seriesCount`, and `hoverAtIndex` / `clickAtIndex` / `waitForHogChartTooltip` for interactions. `createDefaultTooltipAccessor(el)` reads a `DefaultTooltip` by its `hog-chart-tooltip-*` attributes.

Every test file needs the jsdom shims, because the chart measures its container and paints on a frame:

```ts
import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

let cleanupJsdom: () => void
let cleanupRaf: () => void
beforeEach(() => {
  cleanupJsdom = setupJsdom()
  cleanupRaf = setupSyncRaf()
})
afterEach(() => {
  cleanupRaf()
  cleanupJsdom()
})
```

Or call `ensureJsdom()` once at the top of the file when nothing else in the file needs per-test cleanup.

The trends test files are the reference:

- `products/product_analytics/frontend/insights/trends/TrendsLineChart/TrendsLineChart.test.tsx`
- `products/product_analytics/frontend/insights/trends/TrendsBarChart/TrendsBarChart.test.tsx`

Rules:

- Do not mock `@posthog/quill-charts`. A `jest.mock` that captures the chart's props skips the only thing the test could prove.
- Do not query `canvas`, spy on `getContext`, or snapshot pixels. jsdom's canvas is a stub. Assert through the accessor and the tooltip DOM.
- Do not read `scales._private` or React refs.
- Pass an explicit `timeout` to `hoverUntilTooltip` / `clickAtIndex` when the call sits behind another wait, so two 3s budgets do not exceed Jest's 5s per-test limit.
- Keep the cases that catch a regression. An `it.each` matrix whose rows only prove "a canvas rendered" catches nothing.

## Stories

Every new chart component gets a story next to it, and every new library chart, overlay, or config option gets a story in the library package.
Visual review runs on chromium snapshots of these stories.

The insight chart stories follow one shape (`TrendsLineChart.stories.tsx`):

- A `Stage` wrapper with an explicit `height` and `width`. A chart in a zero-height flex child renders nothing.
- `parameters.mockDate` pinned, so the in-progress tail and date labels are stable.
- Fixtures from `~/mocks/fixtures/api/projects/team_id/insights/*.json`, bound through `insightLogic` and `dataNodeLogic` with `doNotLoad: true` and `cachedResults`.
- `testOptions.waitForSelector` pointing at the chart's canvas (`'[data-attr=trend-line-graph] > canvas'`) for full-scene stories, so the snapshot waits for the paint.
- One story per display permutation that changes what the user sees: single series, multi series, breakdown, area, compare, percent stack.

For a chart outside insights, the same rules apply with your own data: stable numbers, a fixed date, an explicit-height stage.

Snapshots of a chart whose canvas paints asynchronously can flake.
The `storybook-skip-chart-canvas` body class sets `theme.skipDraw` through `buildTheme`, which mounts the canvas but skips painting, so overlays and layout stay testable while the pixels stay blank.
Reach for it only when a story flakes on the canvas paint, not by default.

Never snapshot a story built on `Date.now()`, random data, or locale-dependent formatting.
