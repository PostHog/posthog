# Custom chart gallery

Six shapes `@posthog/quill-charts` does not ship, each built the way [custom-shapes.md](custom-shapes.md) describes.
Every example here builds and renders in a canvas; copy the closest one and swap the data.
The first three extend the `Chart` core, so hover and the tooltip are the stock ones.
The last three lay out with d3 and draw their own, sharing the small `chart-kit.tsx` helper at the end.

| Chart       | Question it answers                                 | Pattern    | d3 pieces                                    |
| ----------- | --------------------------------------------------- | ---------- | -------------------------------------------- |
| Bump chart  | How did the rank of the top N change over time?     | Chart core | `scalePoint`, `line` + `curveBumpX`          |
| Ridgeline   | How did a distribution shift per release or cohort? | Chart core | `area` + `curveBasis`, one baseline per row  |
| Waterfall   | What added to and took from a total?                | Chart core | `scaleBand`, running total                   |
| Sunburst    | How do sessions branch through a path hierarchy?    | Raw d3     | `hierarchy`, `partition`, `arc`              |
| Force graph | Which events fire together?                         | Raw d3     | `forceSimulation`, `forceLink`, own canvas   |
| Beeswarm    | What does every session look like, not the summary? | Raw d3     | `forceX`/`forceY`/`forceCollide`, `scaleLog` |

## Bump chart

Rank is the value, so the y scale runs 1 at the top. `yTickFormatter` prints `#n`, and the tooltip keeps series order with `sortedByValue: false`.

```tsx
import { Chart, useChartTheme, type ChartDrawArgs, type ChartScales, type Series } from '@posthog/quill-charts'
import * as d3 from 'd3'

const WEEKS = [
  '2026-08-24',
  '2026-08-31',
  '2026-09-07',
  '2026-09-14',
  '2026-09-21',
  '2026-09-28',
  '2026-10-05',
  '2026-10-12',
]
const RANKS: Record<string, number[]> = {
  '/pricing': [3, 2, 2, 1, 1, 1, 2, 1],
  '/docs': [1, 1, 1, 2, 3, 3, 3, 3],
  '/blog': [2, 3, 3, 3, 2, 2, 1, 2],
  '/signup': [5, 5, 4, 4, 4, 5, 5, 4],
  '/changelog': [4, 4, 5, 5, 5, 4, 4, 5],
}
const SERIES: Series[] = Object.entries(RANKS).map(([key, data]) => ({ key, label: key, data }))

function createScales(series: Series[], labels: string[], dims: ChartDrawArgs['dimensions']): ChartScales {
  const x = d3
    .scalePoint<string>()
    .domain(labels)
    .range([dims.plotLeft + 16, dims.plotLeft + dims.plotWidth - 16])
  const maxRank = d3.max(series, (s) => d3.max(s.data)) ?? 1
  const y = d3
    .scaleLinear()
    .domain([1, maxRank])
    .range([dims.plotTop + 12, dims.plotTop + dims.plotHeight - 12])
  return { x: (label) => x(label), y: (rank) => y(rank), yTicks: () => d3.range(1, maxRank + 1) }
}

function drawStatic({ ctx, scales, series, labels }: ChartDrawArgs): void {
  const line = d3
    .line<number>()
    .x((_, i) => scales.x(labels[i]) ?? 0)
    .y((rank) => scales.y(rank))
    .curve(d3.curveBumpX)
    .context(ctx)
  for (const s of series) {
    ctx.beginPath()
    line(s.data)
    ctx.strokeStyle = s.color
    ctx.lineWidth = 3
    ctx.stroke()
    s.data.forEach((rank, i) => {
      ctx.beginPath()
      ctx.arc(scales.x(labels[i]) ?? 0, scales.y(rank), 5, 0, Math.PI * 2)
      ctx.fillStyle = s.color
      ctx.fill()
    })
  }
}

function drawHover({ ctx, scales, series, labels, hoverIndex }: ChartDrawArgs): boolean {
  if (hoverIndex < 0) return false
  const x = scales.x(labels[hoverIndex]) ?? 0
  for (const s of series) {
    ctx.beginPath()
    ctx.arc(x, scales.y(s.data[hoverIndex]), 8, 0, Math.PI * 2)
    ctx.strokeStyle = s.color
    ctx.lineWidth = 2
    ctx.stroke()
  }
  return true
}

export function BumpChart() {
  const theme = useChartTheme()
  return (
    <Chart
      theme={theme}
      series={SERIES}
      labels={WEEKS}
      createScales={createScales}
      drawStatic={drawStatic}
      drawHover={drawHover}
      config={{
        xTickFormatter: (label) => label.slice(5),
        yTickFormatter: (rank) => `#${rank}`,
        tooltip: { sortedByValue: false, valueFormatter: (rank) => `#${rank}`, placement: 'top' },
      }}
    />
  )
}
```

## Ridgeline

One row per series. `createScales` keeps a baseline per row in `_private`; `scales.y` only has to satisfy the shell, since the rows draw against their own baseline. Rows overlap by `OVERLAP`, and each row's label is painted on the canvas.

```tsx
import { Chart, useChartTheme, type ChartDrawArgs, type ChartScales, type Series } from '@posthog/quill-charts'
import * as d3 from 'd3'

const BUCKETS = Array.from({ length: 30 }, (_, i) => `${i * 200}`)
const bell = (center: number, width: number, height: number) =>
  BUCKETS.map((b) => Math.round(height * Math.exp(-(((Number(b) - center) / width) ** 2))))
const SERIES: Series[] = [
  { key: 'r1', label: 'v1.38', data: bell(1800, 700, 100) },
  { key: 'r2', label: 'v1.39', data: bell(1500, 600, 110) },
  { key: 'r3', label: 'v1.40', data: bell(2200, 900, 80) },
  { key: 'r4', label: 'v1.41', data: bell(1100, 500, 130) },
  { key: 'r5', label: 'v1.42', data: bell(900, 400, 140) },
]
const OVERLAP = 1.6

function createScales(series: Series[], labels: string[], dims: ChartDrawArgs['dimensions']): ChartScales {
  const x = d3
    .scalePoint<string>()
    .domain(labels)
    .range([dims.plotLeft, dims.plotLeft + dims.plotWidth])
  const rowHeight = dims.plotHeight / series.length
  const baseline = (i: number) => dims.plotTop + rowHeight * (i + 1)
  const peak = d3.max(series, (s) => d3.max(s.data)) ?? 1
  const amplitude = d3
    .scaleLinear()
    .domain([0, peak])
    .range([0, rowHeight * OVERLAP])
  return {
    x: (label) => x(label),
    y: (value) => baseline(0) - amplitude(value),
    yTicks: () => [],
    _private: { baseline, amplitude },
  }
}

function drawStatic({ ctx, scales, series, labels, theme }: ChartDrawArgs): void {
  const { baseline, amplitude } = scales._private as {
    baseline: (i: number) => number
    amplitude: (v: number) => number
  }
  series.forEach((s, i) => {
    const area = d3
      .area<number>()
      .x((_, j) => scales.x(labels[j]) ?? 0)
      .y0(baseline(i))
      .y1((v) => baseline(i) - amplitude(v))
      .curve(d3.curveBasis)
      .context(ctx)
    ctx.beginPath()
    area(s.data)
    ctx.fillStyle = s.color
    ctx.globalAlpha = 0.75
    ctx.fill()
    ctx.globalAlpha = 1
    ctx.strokeStyle = theme.backgroundColor ?? '#000'
    ctx.lineWidth = 1.5
    ctx.stroke()
    ctx.fillStyle = theme.axisColor ?? '#888'
    ctx.font = '11px sans-serif'
    ctx.textBaseline = 'bottom'
    ctx.fillText(s.label, (scales.x(labels[0]) ?? 0) + 4, baseline(i) - 2)
  })
}

function drawHover({ ctx, scales, labels, hoverIndex, dimensions, theme }: ChartDrawArgs): boolean {
  if (hoverIndex < 0) return false
  const x = scales.x(labels[hoverIndex]) ?? 0
  ctx.strokeStyle = theme.crosshairColor ?? theme.axisColor ?? '#888'
  ctx.setLineDash([3, 3])
  ctx.beginPath()
  ctx.moveTo(x, dimensions.plotTop)
  ctx.lineTo(x, dimensions.plotTop + dimensions.plotHeight)
  ctx.stroke()
  ctx.setLineDash([])
  return true
}

export function Ridgeline() {
  const theme = useChartTheme()
  return (
    <Chart
      theme={theme}
      series={SERIES}
      labels={BUCKETS}
      createScales={createScales}
      drawStatic={drawStatic}
      drawHover={drawHover}
      config={{
        hideYAxis: true,
        xTickFormatter: (label, i) => (i % 5 === 0 ? `${label}ms` : null),
        tooltip: { placement: 'top', labelFormatter: (label) => `LCP ${label}ms` },
      }}
    />
  )
}
```

## Waterfall

One series of deltas. The first and last entries are totals. `scales.extent` reports the band width so the tooltip anchors on the bar, and `resolveValue` feeds the tooltip the total for total bars and the delta for the rest.

```tsx
import { Chart, useChartTheme, type ChartDrawArgs, type ChartScales, type Series } from '@posthog/quill-charts'
import * as d3 from 'd3'

const STEPS = ['Start of month', 'New signups', 'Reactivated', 'Churned', 'Downgraded', 'End of month']
const DELTAS = [12400, 1850, 320, -940, -210, 0]
const SERIES: Series[] = [{ key: 'mrr', label: 'Active users', data: DELTAS }]

type Bar = { from: number; to: number; total: boolean }

function bars(data: number[]): Bar[] {
  let running = 0
  return data.map((delta, i) => {
    const total = i === 0 || i === data.length - 1
    const from = total ? 0 : running
    running += total && i !== 0 ? 0 : delta
    return { from, to: total ? running : from + delta, total }
  })
}

function createScales(series: Series[], labels: string[], dims: ChartDrawArgs['dimensions']): ChartScales {
  const layout = bars(series[0].data)
  const x = d3
    .scaleBand<string>()
    .domain(labels)
    .range([dims.plotLeft, dims.plotLeft + dims.plotWidth])
    .padding(0.3)
  const y = d3
    .scaleLinear()
    .domain([0, (d3.max(layout, (b) => Math.max(b.from, b.to)) ?? 1) * 1.05])
    .nice()
    .range([dims.plotTop + dims.plotHeight, dims.plotTop])
  return {
    x: (label) => (x(label) ?? 0) + x.bandwidth() / 2,
    y: (value) => y(value),
    yTicks: () => y.ticks(5),
    extent: () => x.bandwidth(),
    _private: { layout, band: x },
  }
}

function drawStatic({ ctx, scales, series, labels, theme }: ChartDrawArgs): void {
  const { layout, band } = scales._private as { layout: Bar[]; band: d3.ScaleBand<string> }
  const [up, down] = [theme.colors[2], theme.colors[4]]
  layout.forEach((bar, i) => {
    const x = band(labels[i]) ?? 0
    const top = scales.y(Math.max(bar.from, bar.to))
    const bottom = scales.y(Math.min(bar.from, bar.to))
    ctx.fillStyle = bar.total ? series[0].color : bar.to >= bar.from ? up : down
    ctx.beginPath()
    ctx.roundRect(x, top, band.bandwidth(), Math.max(bottom - top, 2), 3)
    ctx.fill()
    if (i < layout.length - 1) {
      const next = band(labels[i + 1]) ?? 0
      ctx.strokeStyle = theme.gridColor ?? theme.axisColor ?? '#888'
      ctx.setLineDash([3, 3])
      ctx.beginPath()
      ctx.moveTo(x + band.bandwidth(), scales.y(bar.to))
      ctx.lineTo(next, scales.y(bar.to))
      ctx.stroke()
      ctx.setLineDash([])
    }
  })
}

function drawHover({ ctx, scales, labels, hoverIndex, dimensions }: ChartDrawArgs): boolean {
  if (hoverIndex < 0) return false
  const { band } = scales._private as { band: d3.ScaleBand<string> }
  ctx.fillStyle = 'rgba(255,255,255,0.08)'
  ctx.fillRect(
    (band(labels[hoverIndex]) ?? 0) - band.step() * 0.15,
    dimensions.plotTop,
    band.step(),
    dimensions.plotHeight
  )
  return true
}

export function Waterfall() {
  const theme = useChartTheme()
  const layout = bars(DELTAS)
  return (
    <Chart
      theme={theme}
      series={SERIES}
      labels={STEPS}
      createScales={createScales}
      drawStatic={drawStatic}
      drawHover={drawHover}
      resolveValue={(_, i) => (layout[i].total ? layout[i].to : DELTAS[i])}
      config={{
        showGrid: true,
        yTickFormatter: (v) => d3.format('~s')(v),
        tooltip: { placement: 'top', valueFormatter: (v) => v.toLocaleString('en', { signDisplay: 'exceptZero' }) },
      }}
    />
  )
}
```

## Sunburst

`d3.partition` in polar coordinates. Rings fade by depth, colored by top-level branch. `RadialChart` hit-tests one ring only, so a multi-ring shape draws itself.

```tsx
import { useChartTheme } from '@posthog/quill-charts'
import * as d3 from 'd3'
import { useState } from 'react'
import { cursorIn, TipBox, useSize, type Tip } from './chart-kit'

type Node = { name: string; value?: number; children?: Node[] }

const PATHS: Node = {
  name: 'sessions',
  children: [
    {
      name: '/',
      children: [
        {
          name: '/pricing',
          children: [
            { name: '/signup', value: 420 },
            { name: 'exit', value: 610 },
          ],
        },
        {
          name: '/docs',
          children: [
            { name: '/docs/api', value: 380 },
            { name: 'exit', value: 290 },
          ],
        },
        { name: 'exit', value: 900 },
      ],
    },
    {
      name: '/blog',
      children: [
        { name: '/', value: 310 },
        { name: 'exit', value: 540 },
      ],
    },
    {
      name: '/docs',
      children: [
        { name: '/docs/api', value: 260 },
        { name: '/pricing', value: 120 },
        { name: 'exit', value: 350 },
      ],
    },
  ],
}

export function Sunburst() {
  const theme = useChartTheme()
  const { ref, size } = useSize()
  const [tip, setTip] = useState<Tip | null>(null)
  const radius = Math.min(size.width, size.height) / 2
  const root = d3
    .hierarchy(PATHS)
    .sum((d) => d.value ?? 0)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
  d3.partition<Node>().size([2 * Math.PI, radius])(root)
  const arc = d3
    .arc<d3.HierarchyRectangularNode<Node>>()
    .startAngle((d) => d.x0)
    .endAngle((d) => d.x1)
    .padAngle(0.01)
    .innerRadius((d) => d.y0)
    .outerRadius((d) => d.y1 - 2)
  const top = root.children ?? []
  const colorOf = (d: d3.HierarchyNode<Node>) => {
    const ancestor = d.ancestors().find((n) => n.depth === 1)
    return theme.colors[top.indexOf(ancestor as (typeof top)[number]) % theme.colors.length]
  }
  return (
    <div ref={ref} className="relative h-full w-full" onMouseLeave={() => setTip(null)}>
      {radius > 0 && (
        <svg width={size.width} height={size.height} className="block">
          <g transform={`translate(${size.width / 2},${size.height / 2})`}>
            {(root.descendants() as d3.HierarchyRectangularNode<Node>[])
              .filter((d) => d.depth > 0)
              .map((d) => (
                <path
                  key={d
                    .ancestors()
                    .map((n) => n.data.name)
                    .join('>')}
                  d={arc(d) ?? undefined}
                  fill={colorOf(d)}
                  fillOpacity={1 - (d.depth - 1) * 0.25}
                  onMouseMove={(event) =>
                    setTip({
                      ...cursorIn(ref.current, event),
                      title: d
                        .ancestors()
                        .reverse()
                        .slice(1)
                        .map((n) => n.data.name)
                        .join(' → '),
                      value: `${(d.value ?? 0).toLocaleString()} sessions · ${(((d.value ?? 0) / (root.value ?? 1)) * 100).toFixed(1)}%`,
                      color: colorOf(d),
                    })
                  }
                />
              ))}
          </g>
        </svg>
      )}
      <TipBox tip={tip} theme={theme} />
    </div>
  )
}
```

## Force graph

The simulation paints into its own `<canvas>` on every tick, scaled for the device pixel ratio. Hover is a distance test against the node positions. Stop the simulation in the effect cleanup.

```tsx
import { useChartTheme } from '@posthog/quill-charts'
import * as d3 from 'd3'
import { useEffect, useMemo, useRef, useState } from 'react'
import { cursorIn, TipBox, useSize, type Tip } from './chart-kit'

type NodeDatum = d3.SimulationNodeDatum & { id: string; group: number; weight: number }
type LinkDatum = d3.SimulationLinkDatum<NodeDatum> & { weight: number }

const EVENTS: [string, number, number][] = [
  ['$pageview', 0, 90],
  ['$autocapture', 0, 70],
  ['signed up', 1, 30],
  ['onboarding step', 1, 28],
  ['project created', 1, 22],
  ['insight viewed', 2, 50],
  ['insight saved', 2, 20],
  ['dashboard viewed', 2, 40],
  ['query executed', 2, 45],
  ['recording watched', 3, 25],
  ['flag evaluated', 3, 60],
  ['billing viewed', 1, 12],
]
const LINKS: [string, string, number][] = [
  ['$pageview', '$autocapture', 60],
  ['$pageview', 'signed up', 20],
  ['signed up', 'onboarding step', 25],
  ['onboarding step', 'project created', 20],
  ['project created', 'insight viewed', 15],
  ['insight viewed', 'insight saved', 12],
  ['insight viewed', 'query executed', 30],
  ['dashboard viewed', 'insight viewed', 25],
  ['dashboard viewed', 'query executed', 20],
  ['recording watched', '$pageview', 10],
  ['flag evaluated', '$pageview', 40],
  ['billing viewed', 'project created', 6],
]

export function ForceGraph() {
  const theme = useChartTheme()
  const { ref, size } = useSize()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [tip, setTip] = useState<Tip | null>(null)
  const graph = useMemo(() => {
    const nodes: NodeDatum[] = EVENTS.map(([id, group, weight]) => ({ id, group, weight }))
    const links: LinkDatum[] = LINKS.map(([source, target, weight]) => ({ source, target, weight }))
    return { nodes, links }
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || size.width === 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = size.width * dpr
    canvas.height = size.height * dpr
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    const r = (n: NodeDatum) => 4 + Math.sqrt(n.weight)
    const simulation = d3
      .forceSimulation(graph.nodes)
      .force(
        'link',
        d3
          .forceLink<NodeDatum, LinkDatum>(graph.links)
          .id((d) => d.id)
          .distance((l) => 90 - l.weight / 2)
      )
      .force('charge', d3.forceManyBody().strength(-180))
      .force(
        'collide',
        d3.forceCollide<NodeDatum>((n) => r(n) + 4)
      )
      .force('center', d3.forceCenter(size.width / 2, size.height / 2))
      .on('tick', () => {
        ctx.clearRect(0, 0, size.width, size.height)
        ctx.strokeStyle = theme.gridColor ?? theme.axisColor ?? '#888'
        for (const link of graph.links) {
          const s = link.source as NodeDatum
          const t = link.target as NodeDatum
          ctx.lineWidth = Math.max(1, link.weight / 15)
          ctx.beginPath()
          ctx.moveTo(s.x ?? 0, s.y ?? 0)
          ctx.lineTo(t.x ?? 0, t.y ?? 0)
          ctx.stroke()
        }
        for (const node of graph.nodes) {
          ctx.beginPath()
          ctx.arc(node.x ?? 0, node.y ?? 0, r(node), 0, Math.PI * 2)
          ctx.fillStyle = theme.colors[node.group % theme.colors.length]
          ctx.fill()
          ctx.fillStyle = theme.axisColor ?? '#888'
          ctx.font = '10px sans-serif'
          ctx.fillText(node.id, (node.x ?? 0) + r(node) + 3, (node.y ?? 0) + 3)
        }
      })
    return () => {
      simulation.stop()
    }
  }, [graph, size, theme])

  return (
    <div ref={ref} className="relative h-full w-full" onMouseLeave={() => setTip(null)}>
      <canvas
        ref={canvasRef}
        style={{ width: size.width, height: size.height }}
        onMouseMove={(event) => {
          const { x, y } = cursorIn(ref.current, event)
          const node = graph.nodes.find((n) => Math.hypot((n.x ?? 0) - x, (n.y ?? 0) - y) < 4 + Math.sqrt(n.weight) + 2)
          setTip(
            node
              ? {
                  x,
                  y,
                  title: node.id,
                  value: `${node.weight}k events · ${graph.links.filter((l) => (l.source as NodeDatum).id === node.id || (l.target as NodeDatum).id === node.id).length} links`,
                  color: theme.colors[node.group % theme.colors.length],
                }
              : null
          )
        }}
      />
      <TipBox tip={tip} theme={theme} />
    </div>
  )
}
```

## Beeswarm

A collide force spreads overlapping dots apart. Run it synchronously with `.stop().tick(n)` inside `useMemo`, so the layout is deterministic and does not animate.

```tsx
import { useChartTheme } from '@posthog/quill-charts'
import * as d3 from 'd3'
import { useMemo, useState } from 'react'
import { cursorIn, TipBox, useSize, type Tip } from './chart-kit'

type Session = { id: number; plan: string; seconds: number }

const PLANS = ['Free', 'Startup', 'Scale']
const SESSIONS: Session[] = Array.from({ length: 240 }, (_, i) => {
  const plan = PLANS[i % 3]
  const seed = ((i * 9301 + 49297) % 233280) / 233280
  const base = plan === 'Free' ? 40 : plan === 'Startup' ? 120 : 260
  return { id: i, plan, seconds: Math.round(base * Math.exp((seed - 0.5) * 2.2)) }
})
const R = 4

export function Beeswarm() {
  const theme = useChartTheme()
  const { ref, size } = useSize()
  const [tip, setTip] = useState<Tip | null>(null)
  const margin = { left: 70, right: 16, top: 12, bottom: 28 }
  const x = d3
    .scaleLog()
    .domain([10, 2000])
    .range([margin.left, Math.max(size.width - margin.right, margin.left + 1)])
  const y = d3
    .scaleBand<string>()
    .domain(PLANS)
    .range([margin.top, Math.max(size.height - margin.bottom, margin.top + 1)])
  const dots = useMemo(() => {
    if (size.width === 0) return []
    const nodes = SESSIONS.map((s) => ({ ...s, x: x(s.seconds), y: (y(s.plan) ?? 0) + y.bandwidth() / 2 }))
    d3.forceSimulation(nodes)
      .force('x', d3.forceX<(typeof nodes)[number]>((d) => x(d.seconds)).strength(1))
      .force('y', d3.forceY<(typeof nodes)[number]>((d) => (y(d.plan) ?? 0) + y.bandwidth() / 2).strength(0.1))
      .force('collide', d3.forceCollide(R + 0.5))
      .stop()
      .tick(120)
    return nodes
  }, [size.width, size.height])
  return (
    <div ref={ref} className="relative h-full w-full" onMouseLeave={() => setTip(null)}>
      {size.width > 0 && (
        <svg width={size.width} height={size.height} className="block text-[11px]" fill={theme.axisColor}>
          {PLANS.map((plan) => (
            <text
              key={plan}
              x={margin.left - 10}
              y={(y(plan) ?? 0) + y.bandwidth() / 2}
              textAnchor="end"
              dominantBaseline="middle"
            >
              {plan}
            </text>
          ))}
          {x.ticks(4).map((t) => (
            <g key={t}>
              <line
                x1={x(t)}
                x2={x(t)}
                y1={margin.top}
                y2={size.height - margin.bottom}
                stroke={theme.gridColor}
                strokeDasharray="3 3"
              />
              <text x={x(t)} y={size.height - 8} textAnchor="middle">
                {t >= 60 ? `${Math.round(t / 60)}m` : `${t}s`}
              </text>
            </g>
          ))}
          {dots.map((d) => (
            <circle
              key={d.id}
              cx={d.x}
              cy={d.y}
              r={R}
              fill={theme.colors[PLANS.indexOf(d.plan) % theme.colors.length]}
              fillOpacity={0.85}
              onMouseMove={(event) =>
                setTip({
                  ...cursorIn(ref.current, event),
                  title: `${d.plan} · session ${d.id}`,
                  value: `${d.seconds}s`,
                  color: theme.colors[PLANS.indexOf(d.plan) % theme.colors.length],
                })
              }
            />
          ))}
        </svg>
      )}
      <TipBox tip={tip} theme={theme} />
    </div>
  )
}
```

## chart-kit.tsx

The sizing hook and themed tooltip the raw-d3 examples share. `TooltipSwatch` is context-free; `TooltipSurface` is not, so this draws its own box from `theme.tooltipBackground` and `theme.tooltipColor`.

```tsx
import { TooltipSwatch, type ChartTheme } from '@posthog/quill-charts'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

export type Tip = { x: number; y: number; title: ReactNode; value: ReactNode; color: string }

export function useSize() {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height })
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return { ref, size }
}

export function TipBox({ tip, theme }: { tip: Tip | null; theme: ChartTheme }) {
  if (!tip) return null
  return (
    <div
      className="pointer-events-none absolute z-10 max-w-80 rounded-md border border-white/10 px-2 py-1.5 text-xs shadow-lg"
      style={{ left: tip.x + 12, top: tip.y + 12, backgroundColor: theme.tooltipBackground, color: theme.tooltipColor }}
    >
      <div className="mb-1 font-semibold opacity-60">{tip.title}</div>
      <div className="flex items-center gap-2">
        <TooltipSwatch color={tip.color} />
        <strong className="tabular-nums">{tip.value}</strong>
      </div>
    </div>
  )
}

export function cursorIn(el: HTMLElement | null, event: { clientX: number; clientY: number }) {
  const bounds = el?.getBoundingClientRect()
  return { x: event.clientX - (bounds?.left ?? 0), y: event.clientY - (bounds?.top ?? 0) }
}
```
