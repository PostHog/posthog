---
name: drawing-custom-charts
description: >
  Draws a chart that quill-charts does not ship, or a mark a built-in chart does not draw, in a canvas,
  on the quill-charts core so it keeps the built-in axes, grid lines, hover and tooltip. Use when a canvas
  request names a chart type outside the chart table in building-react-quill-canvases, or asks for an
  annotation, band, callout or other mark on a built-in chart.
---

# Drawing custom charts

Load `building-react-quill-canvases` first for the canvas contract, the allowed imports, the chart table and the type files.
Use a built-in chart when one fits; this skill starts where that table ends.

You already know d3. What you cannot know is how a custom chart joins the PostHog chart system, so it looks and behaves like the built-in charts around it. That is all this skill covers.

## Pick the base

| The shape                                                                                      | Build it on                                                                               |
| ---------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| A built-in chart with one more mark: a target, a release marker, an incident window, a callout | The built-in chart, with `ReferenceLine`, `HighlightedRange` or `ValueLabels` as children |
| One position per label along an x axis: dumbbell, horizon, bump, waterfall, ridgeline          | The `Chart` core                                                                          |
| Angles around a center: chord, sunburst, radial clock                                          | The `RadialChart` core                                                                    |
| No axis at all: treemap, force graph, map                                                      | d3 into an `<svg>`, with a `TooltipSurface` tooltip                                       |

Read the type file for the base before you write it: `Chart.d.ts`, `RadialChart.d.ts`, the overlay files, and `Tooltip.d.ts`, all in `building-react-quill-canvases/references/quill-charts/`.

## The `Chart` core

```tsx
import {
  applyChartDefaults,
  Chart,
  type ChartDrawArgs,
  drawAxes,
  drawGrid,
  resolveAxisLineColor,
  useChartTheme,
} from '@posthog/quill-charts'

function drawDumbbells({ ctx, dimensions, scales, series, labels, theme }: ChartDrawArgs): void {
  drawGrid(
    { ctx, dimensions, yScale: scales.y },
    { gridColor: theme.gridColor, gridDash: theme.gridDashPattern, frame: false, valueTicks: scales.yTicks() }
  )
  // One line and two dots per label go here.
  drawAxes({ ctx, dimensions }, { axisColor: resolveAxisLineColor(theme) })
}

function DumbbellChart({ series, labels }: { series: Series[]; labels: string[] }) {
  const theme = useChartTheme()
  return (
    <div className="flex h-[280px] flex-col">
      <Chart
        series={series}
        labels={labels}
        theme={theme}
        config={applyChartDefaults({ tooltip: { valueFormatter: formatPercent } })}
        createScales={createScales}
        drawStatic={drawDumbbells}
        drawHover={drawHoveredDumbbell}
      />
    </div>
  )
}
```

- `createScales(series, labels, dimensions)` returns `{ x(label), y(value), yTicks() }` in canvas pixels. The core draws the x labels at `x(label)` and the y labels at `yTicks()`.
- In `drawStatic`, call `drawGrid` first and `drawAxes` last, with the arguments above. They draw the same grid lines and axis lines as the built-in charts, on the core's y ticks. Never draw your own grid or axis.
- `applyChartDefaults` turns on the tick marks and crosshair that the core draws, as on the built-in charts.
- Hover resolves along `labels`: `hoverIndex` is the index of the hovered label. Draw its highlight in `drawHover`, and return `false` when nothing was drawn.
- Each series carries the value the tooltip shows at each label in `data`, one entry per label. Put any shape-only numbers, such as a band's lower edge, in `meta`.
- `drawStatic` and `drawHover` get each series with its palette color in `args.series[i].color`. Every other color comes from the theme: `theme.colors`, `theme.gridColor`, `theme.axisColor`.

## The `RadialChart` core

- `buildLayout(series, dimensions)` returns the slices (`startAngle`, `endAngle` in radians, 12 o'clock is 0, clockwise) with `cx`, `cy`, `innerRadius` and `outerRadius`.
- The core draws nothing itself. Draw the ring, its labels and everything inside it in `drawStatic`, and the hovered slice in `drawHover`.
- `drawStatic` and `drawHover` do not receive the layout. Keep the one `buildLayout` returns in a ref and draw from it.
- Hover hits a slice by its angle within the ring. `hoverIndex` is that slice's index in `series`.
- The tooltip gets one row for the hovered slice: its series, value, color and `fraction`.

## Tooltips

Never write a tooltip from scratch. The built-in tooltip pieces keep every chart's tooltip the same.

- On either core, leave `tooltip` unset for the built-in `DefaultTooltip`: the label, then one row per series at the hovered index. Format it through `config.tooltip` (`valueFormatter`, `labelFormatter`, `showTotal`).
- For other content, return `<DefaultTooltip {...ctx} />` with `labelRenderer`, `valueFormatter` or `showHeader`. For rows it cannot express, compose `TooltipSurface` with `TooltipSwatch` and `TooltipFooter`.
- With no core, render a `TooltipSurface` yourself, positioned at the cursor inside a `relative` wrapper.

## Layout around the chart

- Size the chart with a fixed-height flex column, like the built-in charts. The core fills it.
- Put row labels beside a chart in a `shrink-0` column wide enough for the longest label, in small text (`text-xs`). Do not `truncate` a label that carries a value, such as a scale or a unit.
