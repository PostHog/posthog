# Contributing to quill-charts

For people working on the library itself: adding a chart type, changing the draw loop, extending overlays. If you're embedding a chart in product code, read the [README](../README.md) instead.

## Layers

| Layer                                                    | What goes here                                                                                                 |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Chart types** (`charts/<Name>/`)                       | Everything one chart type owns: its component, scales, layout geometry, drawing, hooks, tooltip and types.     |
| **Chart base** (`core/`)                                 | Code that two or more chart types share: the base `Chart`, the draw loop, interaction, context, shared scales. |
| **Shared canvas primitives** (`core/canvas-renderer.ts`) | Stateless drawing functions that more than one chart type uses, such as the grid, axes, lines and bars.        |
| **Overlays** (`overlays/`)                               | React DOM components drawn on top of the canvas, such as value labels and reference lines.                     |

Where new code goes:

- Code lives with its users. Code that one chart type uses stays in `charts/<Name>/`, next to its test. Code that two or more chart types use goes in `core/`. When a second chart type needs code from a chart folder, move that code to `core/` in the same PR.
- Drawing functions are stateless and free of React, wherever they live. A chart's own drawing goes in `charts/<Name>/draw-<name>.ts`.
- One component per file. Do not build JSX in a `renderX()` helper; extract a component. A chart-specific tooltip is a pure function that shapes the tooltip context, plus a named tooltip component.
- DOM overlays go in `overlays/<Name>.tsx` and read context through `useChartLayout()` / `useChartHover()`.

## Render model

Read this before you add a hook, a memo or an overlay.

- **`Chart` re-renders on every mousemove**, because it holds the hover state. Anything it renders inline runs per mousemove. Keep that work cheap, or wrap the component in `React.memo` and pass it stable props.
- **Two canvases.** The static canvas repaints when its inputs change identity: `series`, `labels`, `theme`, the dimensions, `createScales` and `drawStatic`. The hover canvas repaints when the hover changes. Static drawing never moves onto the hover path.
- **Must be stable** (a module-level function, or a memo keyed on the real inputs): `series`, `labels`, `createScales`, `drawStatic`, and every object or function they read, such as `valueDomain`, `yAxes` and tick formatters.
- **Need not be stable:** event callbacks (`onPointClick`, `onAreaSelect`, `resolveValue` and the other resolvers), which the interaction hooks read through refs; the `tooltip` render prop; and the `config` object itself, which `Chart` destructures.
- **Memoize only when identity matters**, or when the work is expensive and runs per mousemove. A memo around cheap work, or around a value whose consumer ignores identity, adds lines and does nothing.
- **Scale target: 1,000 series × 100,000 points.** No quadratic work over the dataset. Hover costs O(1) or O(log n) per mousemove, allocates nothing per series, and never repaints the static canvas. Precompute on data change and index on hover.

## API conventions

New props and config keys use these names and shapes. Some older charts still differ, and [#123088](https://github.com/PostHog/posthog/issues/123088) tracks moving them over. Before you add a prop, find the same concept in a sibling chart and match its name, shape and default. When no chart has it yet, add the convention here.

- **Props or config:** data and content are props (`series`, `labels`, render props, `ReactNode`). Options are keys in `config`.
- **Formatting:** a chart-wide value formatter is `config.valueFormatter: (value: number) => string`. Formatting that only the tooltip uses goes in `config.tooltip`.
- **Legend:** `config.legend: ChartLegendConfig`, not a boolean.
- **Tooltip:** `config.tooltip` reuses the shared tooltip config fields (`enabled`, `placement`). Custom content comes through the `tooltip` render prop.
- **Axes:** nested `config.xAxis` and `config.yAxis`, reusing the field names of `XAxisConfig` and `YAxisConfig` in `utils/use-axis-formatters.ts`. For example, the log or linear option is `scale`, not `scaleType`.
- **Animation:** `animationMs: number`, where `0` turns animation off.
- **Selection:** a drag along x reports through `onRangeSelect`. A 2D brush reports through `onAreaSelect`.
- **State:** a `default*` prop is read on mount only. State the parent controls is a pair, such as `focusedId` and `onFocusChange`.
- **Errors:** every chart takes `onError`. A chart that wraps another chart passes `onError` to it.
- **Shared props:** a prop that every chart takes goes on a shared base props type. Do not add it to each chart by hand.
- **Scope:** every new prop, option or mode has a caller in the PR or a named consumer. Do not add options for later.

## The custom chart API

Code outside the library builds chart types the library does not ship on top of `Chart`, `RadialChart`, `drawGrid`, `drawAxes`, `resolveAxisLineColor`, `applyChartDefaults`, the core types and the tooltip pieces. The main planned user is generated canvas charts: the canvas builder pins a published version of this package, and a canvas skill teaches this API ([#120197](https://github.com/PostHog/posthog/pull/120197)). So:

- `ChartProps`, `ChartDrawArgs`, `ChartScales` and those exports are public API, even when no file in this repo uses them. Check the canvas skills under `products/canvas/skills/` before you remove or rename an export.
- A new prop on the base `Chart` is generic: it names no chart type's concept, and no existing seam already covers it.
- A breaking change to this API needs a deprecation step. When the canvas pin moves to a version that changes it, update the canvas skills in the same PR.

## Conventions

- **No kea, no PostHog imports.** Theme, colors, and data are passed in as props. The library has no app dependencies. Trends uses it, but the library does not know about trends.
- **`ChartScales` must not expose d3 types.** Public interface is `x(label) => px`, `y(value) => px`, `yTicks() => number[]`. d3 stays inside the chart type's `createScales`.
- **Chart-private state goes in `scales._private`,** not in a `useRef`. This avoids races between `createScales` and the draw loop in strict and concurrent mode.
- **Overlays use the granular hooks.** `useChartLayout()` doesn't re-render on hover; `useChartHover()` does. Use `useChart()` only when an overlay genuinely needs both. It re-renders on every mousemove.
- **Pure logic is tested directly, next to its file.** Chart-level tests assert on the rendered DOM through the `HogChart` accessor. See [TESTING.md](./TESTING.md).

## Adding a new chart type

```tsx
import { Chart } from '../../core/Chart'
import type { ChartDrawArgs, ChartScales } from '../../core/types'

function createScales(series: ResolvedSeries[], labels: string[], dimensions: ChartDimensions): ChartScales {
  // Use d3.scaleBand for the x-axis instead of scalePoint
  return { x, y, yTicks: () => yScale.ticks() }
}

function drawStatic({ ctx, dimensions, scales, theme }: ChartDrawArgs): void {
  drawGrid(
    { ctx, dimensions, yScale: scales.y },
    { gridColor: theme.gridColor, gridDash: theme.gridDashPattern, frame: false, valueTicks: scales.yTicks() }
  )
  // Draw bars using shared canvas primitives or this chart's own draw file
  drawAxes({ ctx, dimensions }, { axisColor: resolveAxisLineColor(theme) })
}

function drawHover({ ctx, hoverIndex }: ChartDrawArgs): boolean {
  // Highlight the hovered bar; return false when nothing was drawn
}

export function BarChart({ series, labels, config, theme, ...props }: BarChartProps): React.ReactElement {
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

- `createScales`, `drawStatic` and `drawHover` are module-level functions, so their identity never changes. When one needs a prop, memoize it on exactly the values it reads.
- `applyChartDefaults` turns on the tick marks and crosshair, as on the built-in charts. The core reads them from `config` and treats a missing switch as off.
- `drawStatic` draws the grid lines first and the axis lines last, as the built-in charts do. `valueTicks: scales.yTicks()` puts the grid lines on the y-axis labels, and `frame: false` leaves the plot edges to `drawAxes`. Code outside the library imports `drawGrid`, `drawAxes` and `resolveAxisLineColor` from the package.
- Leave `tooltip` unset for the stock `DefaultTooltip`, configured through `config.tooltip`. For other content, return `DefaultTooltip` with a `labelRenderer` or `valueFormatter`, or compose `TooltipSurface` and `TooltipSwatch`, so the tooltip still matches the built-in charts.
