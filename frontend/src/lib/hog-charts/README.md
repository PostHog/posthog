# hog-charts

PostHog's canvas-based charting library built on D3.

## Layers

| Layer                                            | What goes here                                                                                        |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| **Chart types** (`charts/`)                      | Chart-specific logic — e.g. line vs bar. Provides `createScales` and `draw` to the base Chart.        |
| **Chart base** (`core/`)                         | Generic chart infrastructure shared by all types — canvas, draw loop, interaction, overlays, context. |
| **Canvas rendering** (`core/canvas-renderer.ts`) | Stateless pure functions that draw to a canvas. All drawing code goes here.                           |
| **Overlays** (`overlays/`)                       | React DOM components rendered on top of the canvas e.g. annotations                                   |

## Rules

- **No kea, no PostHog imports.** Theme, colors, and data are passed in as
  props.
- **`ChartScales` must not expose d3 types.** Public interface is
  `x(label) => px`, `y(value) => px`, `yTicks() => number[]`.
- **Canvas functions are stateless.** Pure functions in `canvas-renderer.ts`, no
  React or side effects.
- **Overlays use `useChartLayout()` / `useChartHover()` (or `useChart()` for both),
  not props from Chart.** Prefer the granular hooks: `useChartLayout()` doesn't
  re-render on hover, while `useChartHover()` does. Use `useChart()` only when an
  overlay needs both — it re-renders on every mousemove.
- **Tests go through the accessor.** Chart-level tests use `renderHogChart` plus
  the `HogChart` accessor from `testing/`. The `data-attr` selectors are a
  stable contract. Drive interactions with `hoverAtIndex` / `clickAtIndex` /
  `waitForHogChartTooltip`. Don't mock `canvas-renderer` from chart tests —
  pure logic is tested at the `core/` layer. See [docs/TESTING.md](./docs/TESTING.md).

## Adding a new chart type

```tsx
import { Chart } from '../core/Chart'
import type { ChartDrawArgs, ChartScales, CreateScalesFn } from '../core/types'

export function BarChart({ series, labels, config, theme, ...props }: BarChartProps) {
  const createScales: CreateScalesFn = useCallback((coloredSeries, scaleLabels, dimensions) => {
    // Use d3.scaleBand for x-axis instead of scalePoint
    return { x, y, yTicks: () => yScale.ticks() }
  }, [])

  const draw = useCallback(({ ctx, dimensions, scales, series, labels, hoverIndex }: ChartDrawArgs) => {
    // Draw bars using canvas-renderer primitives or custom drawing
  }, [])

  return (
    <Chart
      series={series}
      labels={labels}
      config={config}
      theme={theme}
      createScales={createScales}
      draw={draw}
      {...props}
    >
      {/* Bar-chart-specific overlays as children */}
    </Chart>
  )
}
```

## Public API

```tsx
import { LineChart } from 'lib/hog-charts'
import type { ChartTheme, LineChartConfig, Series } from 'lib/hog-charts'
```

For custom overlays rendered as children, use `useChartLayout()` to read scales,
dimensions, theme, and resolved values; use `useChartHover()` if the overlay
reacts to the hovered data point. `useChart()` returns the merged shape and is
kept for back-compat.

For custom tooltip content, pass a component to the `tooltip` prop. It receives
`TooltipContext` as props. Omit to use the built-in `DefaultTooltip`.

### Series role and visibility

- `series.overlay` (default `false`): marks an auxiliary series derived from
  primary data — trend lines and moving averages. Excluded from stack
  computation and from the y-axis baseline calculation, so a trendline
  projection won't drag the axis below 0 when the underlying data is
  non-negative. (CI bands are not overlays — they represent real data
  uncertainty whose range should still influence the axis.)

The `series.visibility` object controls where a series appears:

- `excluded` (default `false`): fully excludes the series — no rendering, no
  scale contribution, no tooltip row, no hit-testing.
- `tooltip` (default `true`): when `false`, the series still renders and
  participates in scales and hit-testing, but is omitted from
  `TooltipContext.seriesData` so it doesn't appear as a tooltip row.
- `valueLabel` (default `true`): when `false`, the `ValueLabels` overlay
  skips this series.
