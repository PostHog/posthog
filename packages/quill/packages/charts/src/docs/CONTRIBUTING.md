# Contributing to hog-charts

For people working on the library itself — adding a chart type, adjusting the draw loop, extending overlays. If you're embedding a chart in product code, read the [README](../README.md) instead.

## Layers

| Layer                                            | What goes here                                                                                        |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| **Chart types** (`charts/`)                      | Chart-specific logic — e.g. line vs bar. Provides `createScales` and `draw` to the base Chart.        |
| **Chart base** (`core/`)                         | Generic chart infrastructure shared by all types — canvas, draw loop, interaction, overlays, context. |
| **Canvas rendering** (`core/canvas-renderer.ts`) | Stateless pure functions that draw to a canvas. All drawing code goes here.                           |
| **Overlays** (`overlays/`)                       | React DOM components rendered on top of the canvas, e.g. annotations, value labels, reference lines.  |

Where new code goes:

- Pure geometry (scales, layouts) → `core/scales.ts`, `core/bar-layout.ts`, or a sibling. Test these directly under `core/`.
- Drawing primitives → `core/canvas-renderer.ts`. Stateless, no React.
- Chart-type React → `charts/<name>/<Name>.tsx`.
- DOM overlays → `overlays/<Name>.tsx`. Read context via `useChartLayout()` / `useChartHover()`.

## Conventions

- **No kea, no PostHog imports.** Theme, colors, and data are passed in as props. The library has no app dependencies — it's used by trends but shouldn't know about them.
- **`ChartScales` must not expose d3 types.** Public interface is `x(label) => px`, `y(value) => px`, `yTicks() => number[]`. d3 stays inside the chart-type's `createScales`.
- **Canvas functions are stateless.** Pure functions in `canvas-renderer.ts`, no React or side effects. State lives in React; drawing reads it.
- **Overlays use the granular hooks.** `useChartLayout()` doesn't re-render on hover; `useChartHover()` does. Use `useChart()` only when an overlay genuinely needs both — it re-renders on every mousemove.
- **Pure logic is tested at the `core/` layer.** Chart-level tests assert on the rendered DOM through the `HogChart` accessor — see [TESTING.md](./TESTING.md).

## Adding a new chart type

```tsx
import { Chart } from '../core/Chart'
import type { ChartDrawArgs, ChartScales, CreateScalesFn } from '../core/types'

export function BarChart({ series, labels, config, theme, ...props }: BarChartProps) {
  const createScales: CreateScalesFn = useCallback((coloredSeries, scaleLabels, dimensions) => {
    // Use d3.scaleBand for x-axis instead of scalePoint
    return { x, y, yTicks: () => yScale.ticks() }
  }, [])

  const drawStatic = useCallback(({ ctx, dimensions, scales, series, labels, theme }: ChartDrawArgs) => {
    drawGrid(
      { ctx, dimensions, yScale: scales.y },
      { gridColor: theme.gridColor, gridDash: theme.gridDashPattern, frame: false, valueTicks: scales.yTicks() }
    )
    // Draw bars using canvas-renderer primitives or custom drawing
    drawAxes({ ctx, dimensions }, { axisColor: resolveAxisLineColor(theme) })
  }, [])

  const drawHover = useCallback(({ ctx, hoverIndex }: ChartDrawArgs) => {
    // Highlight the hovered bar; return false when nothing was drawn
  }, [])

  return (
    <Chart
      series={series}
      labels={labels}
      config={applyChartDefaults(config)}
      theme={theme}
      createScales={createScales}
      drawStatic={drawStatic}
      drawHover={drawHover}
      {...props}
    >
      {/* Bar-chart-specific overlays as children */}
    </Chart>
  )
}
```

- `applyChartDefaults` turns on the tick marks and crosshair, as on the built-in charts. The core reads them from `config` and treats a missing switch as off.
- `drawStatic` draws the grid lines first and the axis lines last, as the built-in charts do. `valueTicks: scales.yTicks()` puts the grid lines on the y-axis labels, and `frame: false` leaves the plot edges to `drawAxes`. Code outside the library imports `drawGrid`, `drawAxes` and `resolveAxisLineColor` from the package.
- Leave `tooltip` unset for the stock `DefaultTooltip`, configured through `config.tooltip`. For other content, return `DefaultTooltip` with a `labelRenderer` or `valueFormatter`, or compose `TooltipSurface` and `TooltipSwatch`, so the tooltip still matches the built-in charts.
