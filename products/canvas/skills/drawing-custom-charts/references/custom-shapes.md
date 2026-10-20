# Custom charts

Read this when the chart table in `building-react-quill-canvases/references/platform-libraries.md` has nothing that fits.
Stock charts come with legends, value labels, drag-to-zoom and click payloads, so exhaust them first: a stacked `TimeSeriesBarChart` or a `ComboChart` covers more than it looks.

There are two ways to draw a shape the library does not ship, and the data decides which.
[gallery.md](gallery.md) has six worked examples: bump chart, ridgeline, waterfall, sunburst, force graph, beeswarm.

## 1. Data on a category axis: extend the `Chart` core

`Chart` is the shell every axis chart in `@posthog/quill-charts` is built on.
It owns the `<canvas>`, device-pixel scaling, resize, margins, the x-axis ticks, hover-index resolution along `labels`, the tooltip, and the overlay layer.
You supply three functions, and d3 does the geometry.

```tsx
import { Chart, useChartTheme, type ChartDrawArgs, type ChartScales, type Series } from '@posthog/quill-charts'
import * as d3 from 'd3'

type Layer = d3.Series<number, string>

function createScales(series: Series[], labels: string[], dims: ChartDrawArgs['dimensions']): ChartScales {
  const rows = labels.map((_, i) => Object.fromEntries(series.map((s) => [s.key, s.data[i]])))
  const layers = d3
    .stack<Record<string, number>>()
    .keys(series.map((s) => s.key))
    .offset(d3.stackOffsetWiggle)(rows)
  const flat = layers.flat()
  const x = d3
    .scalePoint<string>()
    .domain(labels)
    .range([dims.plotLeft, dims.plotLeft + dims.plotWidth])
  const y = d3
    .scaleLinear()
    .domain([d3.min(flat, (d) => d[0]) ?? 0, d3.max(flat, (d) => d[1]) ?? 1])
    .nice()
    .range([dims.plotTop + dims.plotHeight, dims.plotTop])
  return { x: (label) => x(label), y: (value) => y(value), yTicks: () => y.ticks(5), _private: { layers } }
}

function drawStatic({ ctx, scales, series, labels }: ChartDrawArgs): void {
  const { layers } = scales._private as { layers: Layer[] }
  const area = d3
    .area<[number, number]>()
    .x((_, i) => scales.x(labels[i]) ?? 0)
    .y0((d) => scales.y(d[0]))
    .y1((d) => scales.y(d[1]))
    .curve(d3.curveBasis)
    .context(ctx)
  layers.forEach((layer, i) => {
    ctx.beginPath()
    area(layer as unknown as [number, number][])
    ctx.fillStyle = series[i].color
    ctx.fill()
  })
}

function drawHover({ ctx, scales, labels, hoverIndex, dimensions, theme }: ChartDrawArgs): boolean {
  if (hoverIndex < 0) return false
  const x = scales.x(labels[hoverIndex]) ?? 0
  ctx.strokeStyle = theme.crosshairColor ?? theme.axisColor ?? '#888'
  ctx.beginPath()
  ctx.moveTo(x, dimensions.plotTop)
  ctx.lineTo(x, dimensions.plotTop + dimensions.plotHeight)
  ctx.stroke()
  return true
}

function Streamgraph({ labels, series }: { labels: string[]; series: Series[] }) {
  const theme = useChartTheme()
  return (
    <Chart
      theme={theme}
      series={series}
      labels={labels}
      createScales={createScales}
      drawStatic={drawStatic}
      drawHover={drawHover}
      config={{ hideYAxis: true, tooltip: { showTotal: true, placement: 'top' } }}
    />
  )
}
```

The contract:

- `createScales(series, labels, dimensions)` returns `{ x, y, yTicks }`. `x` maps a label to a pixel, `y` maps a value to a pixel, `yTicks` feeds the y-axis labels. Put anything the draw functions need in `_private`.
- `drawStatic` paints the data. It runs once per data or size change, never on hover.
- `drawHover` paints the highlight for `hoverIndex` and returns whether it drew anything. Keep it cheap, it runs on every mouse move.
- `series[i].color` is already resolved from the palette by the time either runs. Do not pick colors yourself.
- `ctx` is the shell's 2D context, already scaled for the device. Draw into it. Do not create a second `<canvas>`.
- `dimensions` gives `plotLeft`, `plotTop`, `plotWidth`, `plotHeight`. Stay inside them so the axes line up.
- The same wrapper rule applies: `<div className="flex h-[320px] flex-col">` around the chart.
- `config` is the base `ChartConfig`: `xTickFormatter`, `yTickFormatter`, `hideXAxis`, `hideYAxis`, `showGrid`, `tooltip`, `margins`.
- `children` render in the overlay layer. `ReferenceLine`, `HighlightedRange` and any component that calls `useChartLayout()` work unchanged.

The shell resolves hover along `labels`, so this path needs one label per x position.
Pass `resolveValue` when a series's tooltip value is not `series.data[index]`.

`RadialChart` is the same seam for polar shapes: `buildLayout` returns the slices, `drawStatic` and `drawHover` paint them, and the shell owns the tooltip and `onSliceClick`.

## 2. Data with no category axis: raw d3 with the chart theme

A treemap, a force graph, a chord diagram or a map has no `labels`, so the `Chart` shell has nothing to resolve hover against.
Lay it out with d3 and render it yourself, as SVG in React or into your own `<canvas>`.
Take colors from `useChartTheme()` so it matches the charts beside it.

```tsx
import { TooltipSwatch, useChartTheme } from '@posthog/quill-charts'
import * as d3 from 'd3'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'

type Node = { name: string; value?: number; children?: Node[] }
type Hover = { x: number; y: number; name: string; value: number; color: string }

function Treemap({ data }: { data: Node }) {
  const theme = useChartTheme()
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [hover, setHover] = useState<Hover | null>(null)
  useLayoutEffect(() => {
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
    )
    observer.observe(ref.current!)
    return () => observer.disconnect()
  }, [])
  const leaves = useMemo(() => {
    const root = d3
      .hierarchy(data)
      .sum((d) => d.value ?? 0)
      .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
    d3.treemap<Node>().size([size.width, size.height]).paddingInner(2).round(true)(root)
    const colorByGroup = new Map(
      (root.children ?? []).map((group, i) => [group, theme.colors[i % theme.colors.length]])
    )
    return root.leaves().map((leaf) => ({
      leaf,
      key: leaf
        .ancestors()
        .map((n) => n.data.name)
        .join('/'),
      color: colorByGroup.get(leaf.ancestors().find((n) => n.depth === 1)!) ?? theme.colors[0],
    }))
  }, [data, size, theme])
  return (
    <div ref={ref} className="relative h-full w-full" onMouseLeave={() => setHover(null)}>
      {size.width > 0 && (
        <svg width={size.width} height={size.height} className="block">
          {leaves.map(({ leaf, key, color }) => (
            <rect
              key={key}
              x={leaf.x0}
              y={leaf.y0}
              width={leaf.x1 - leaf.x0}
              height={leaf.y1 - leaf.y0}
              rx={3}
              fill={color}
              fillOpacity={hover?.name === leaf.data.name ? 1 : 0.85}
              onMouseMove={(event) => {
                const bounds = ref.current!.getBoundingClientRect()
                setHover({
                  x: event.clientX - bounds.left,
                  y: event.clientY - bounds.top,
                  name: leaf.data.name,
                  value: leaf.value ?? 0,
                  color,
                })
              }}
            />
          ))}
        </svg>
      )}
      {hover && (
        <div
          className="pointer-events-none absolute z-10 flex items-center gap-2 rounded-md border border-white/10 px-2 py-1.5 text-xs shadow-lg"
          style={{
            left: hover.x + 12,
            top: hover.y + 12,
            backgroundColor: theme.tooltipBackground,
            color: theme.tooltipColor,
          }}
        >
          <TooltipSwatch color={hover.color} />
          <span>{hover.name}</span>
          <strong className="ml-auto tabular-nums">{hover.value.toLocaleString()}</strong>
        </div>
      )}
    </div>
  )
}
```

- Measure the container with a `ResizeObserver` and render nothing until it has a size. A fixed-height parent (`h-[320px]`) gives it one.
- Lay out in a `useMemo` keyed on data, size and theme. Hover is state, so without it every mouse move re-runs the layout, and a large hierarchy makes the tooltip stutter.
- Colors: `theme.colors[i]` for data, `theme.axisColor` and `theme.gridColor` for lines and labels. Never a hardcoded hex, and never a UI token such as `bg-primary` for data.
- Tooltips: track the hovered item in state and render a div at the cursor, colored with `theme.tooltipBackground` and `theme.tooltipColor` so it matches the stock charts' tooltip. `TooltipSwatch` from `@posthog/quill-charts` draws the color dot. `TooltipSurface` and `DefaultTooltip` read the chart context and throw outside a `Chart`, so they are for pattern 1 only. Do not rely on an SVG `<title>`: it appears after a delay, only while the mouse is still, and in the browser's own style.
- `d3` is the full build (`d3-hierarchy`, `d3-force`, `d3-geo`, `d3-chord`, `d3-sankey` is not included).
