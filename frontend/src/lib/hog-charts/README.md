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
- **Overlays use `useChart()`, not props from Chart.**

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

For custom overlays rendered as children, use `useChart()` to access scales,
dimensions, and hover state.

For custom tooltip content, pass a component to the `tooltip` prop. It receives
`TooltipContext` as props. Omit to use the built-in `DefaultTooltip`.

### Series visibility flags

- `hidden`: fully excludes the series — no rendering, no scale contribution, no
  tooltip row, no hit-testing.
- `hideFromTooltip`: the series still renders and participates in scales and
  hit-testing, but is omitted from `TooltipContext.seriesData` so it doesn't
  appear as a tooltip row. Useful for background/reference series that
  shouldn't clutter the tooltip.
