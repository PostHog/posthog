# Platform libraries

The canvas builder pins ten optional libraries. Choose the smallest one that matches the job and
keep the dependency map returned by `canvas-source-retrieve` unchanged.

| Library                   | Use it for                  | Main capabilities                                                                            |
| ------------------------- | --------------------------- | -------------------------------------------------------------------------------------------- |
| `d3`                      | Bespoke data visualization  | Scales, shapes, layouts, geographic projections, interpolation, and SVG helpers              |
| `three`                   | 3D and WebGL scenes         | Cameras, geometry, materials, lighting, animation, and raycasting                            |
| `framer-motion`           | Coordinated React animation | Enter and exit transitions, layout animation, gestures, springs, and reduced-motion handling |
| `zod`                     | Runtime data validation     | Schemas, parsing, coercion, transformations, unions, and typed validation errors             |
| `@tanstack/react-table`   | Complex data tables         | Sorting, filtering, grouping, pagination, selection, and column state                        |
| `@tanstack/react-virtual` | Large tables and lists      | Windowed rows and columns, dynamic measurements, scrolling, and overscan                     |
| `react-hook-form`         | Multi-field forms           | Field registration, validation, dirty state, controlled inputs, and submission state         |
| `lodash-es`               | Data transformation         | Grouping, ordering, deduplication, aggregation, object selection, and collection helpers     |
| `react-markdown`          | Safe Markdown presentation  | Markdown parsing into React elements without `dangerouslySetInnerHTML`                       |
| `papaparse`               | CSV input and output        | CSV parsing, header mapping, type conversion, malformed-row reporting, and CSV generation    |

## Selection guidance

- Use `@posthog/quill-charts` for charts. Use D3 for a layout, projection, or shape that quill-charts does not
  provide, following the `drawing-custom-charts` skill.
- Prefer Quill's `Table` for small static tables. Use TanStack Table for table behavior and TanStack
  Virtual when the rendered row count is large. These libraries provide behavior, not visual styles.
- Use React Hook Form with Quill inputs. Keep the network submit button disabled while submission is
  active.
- Use Zod at untrusted boundaries, including declared external API responses and parsed CSV rows.
- Use lodash-es named imports so the builder can remove unused helpers.
- React Markdown does not enable raw HTML by default. Do not add plugins or renderers that execute
  HTML from untrusted content.
- Papa Parse processes text already available to the canvas. Loading a remote CSV still requires its
  exact HTTPS origin in `capabilities.network.origins` (published canvases only — the edit-mode
  preview blocks direct network access regardless of declaration). The same declaration is required
  for external stylesheets, images, fonts, media, and frames.
- Three.js owns its `<canvas>` element. React can own the surrounding Quill application shell.

The standard imports remain `react`, `react-dom`, `react-dom/client`, `@posthog/quill`, `@posthog/quill-charts`,
`lucide-react`, and `dayjs`.

## Charts

`@posthog/quill-charts` draws on a `<canvas>` and takes its colors from the PostHog data palette in the Quill tokens.
Every chart takes `theme={useChartTheme()}`.
The axis charts need a parent like `<div className="flex h-[280px] flex-col">`; `BarList`, `ProportionBar`, `Sparkline` and `MetricCard` size themselves.

| Chart                                 | Use it for                                                                                                                                                    |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `TimeSeriesLineChart`                 | Trends over dates. Add `fill: {}` to a series for an area. Config takes `goalLines`, `trendLines`, `movingAverage`                                            |
| `TimeSeriesBarChart`                  | Bars over dates. `config.barLayout`: `"stacked"` (default), `"grouped"`, or `"percent"`                                                                       |
| `TimeSeriesComboChart`                | Bars and lines on one date axis. Set `type: "bar" \| "line" \| "area"` on each series                                                                         |
| `LineChart`, `BarChart`, `ComboChart` | The same charts over categories that are not dates. `BarChart` takes `config.axisOrientation: "horizontal"`                                                   |
| `BarList`                             | A ranked list: one series per row, a label, a bar on a neutral track, and the value. Top events, top pages, top referrers                                     |
| `ProportionBar`                       | A share of a whole as one segmented bar with a legend: one series per part. Category mix, browser share                                                       |
| `PieChart`                            | Part of a whole as a circle. One series per slice. `config.innerRadiusRatio: 0.5` for a donut, `centerLabel` for the total                                    |
| `FunnelChart`                         | Funnel steps. `funnelFromCounts` builds its input from step counts                                                                                            |
| `ScatterChart`                        | Two numeric axes. Each series takes `points`, not `data`                                                                                                      |
| `Heatmap`                             | A grid of values, such as activity by day and hour. Takes `xLabels`, `yLabels` and `cells[row][col]`                                                          |
| `BoxPlot`                             | Distributions                                                                                                                                                 |
| `SlopeChart`                          | Change between two points                                                                                                                                     |
| `Sparkline`                           | A small trend with no axes. Takes `data` and a `height` prop instead of a sized parent. Its `fill` prop means "fill a flex parent's height", not an area fill |
| `MetricCard`                          | A headline number with a sparkline and a change pill                                                                                                          |
| `Chart`, `RadialChart`                | The core the charts above are built on. Extend it for a shape that is not listed, following the `drawing-custom-charts` skill                                 |

```tsx
import dayjs from 'dayjs'
import { TimeSeriesLineChart, useChartTheme } from '@posthog/quill-charts'

function Trend({ days, values }) {
  const theme = useChartTheme()
  return (
    <div className="flex h-[280px] flex-col">
      <TimeSeriesLineChart
        theme={theme}
        labels={days}
        series={[{ key: 'events', label: 'Events', data: values }]}
        config={{ xAxis: { interval: 'day', tickFormatter: (day) => dayjs(day).format('MMM D') } }}
      />
    </div>
  )
}
```

```tsx
import { BarList, ProportionBar, useChartTheme } from '@posthog/quill-charts'

const formatNumber = (value: number) => value.toLocaleString()

function TopEvents({ rows }: { rows: { event: string; count: number }[] }) {
  const theme = useChartTheme()
  const series = rows.map((row) => ({ key: row.event, label: row.event, data: [row.count] }))
  return <BarList theme={theme} series={series} valueFormatter={formatNumber} config={{ valueDisplay: 'both' }} />
}

function CategoryMix({ parts }: { parts: { label: string; value: number }[] }) {
  const theme = useChartTheme()
  const series = parts.map((part) => ({ key: part.label, label: part.label, data: [part.value] }))
  return <ProportionBar theme={theme} series={series} valueFormatter={formatNumber} />
}
```

- Time-series charts take ISO date strings as `labels`, and labels must be unique.
- The time-series charts format through `config.xAxis.tickFormatter`, `config.yAxis.tickFormatter` and `config.tooltip.valueFormatter`. `BarChart`, `LineChart` and `ComboChart` take `config.xTickFormatter` and `config.yTickFormatter` at the top level instead; a `yAxis` key on them is ignored.
- `BarList`, `ProportionBar` and `PieChart` value a series as the sum of its `data`, so pass one value per series. `BarList` keeps the order of `series`, so sort rows first, and takes `total` when the rows are the top of a larger whole.
- A horizontal `BarChart` grows its container to fit 24px per row. Inside a fixed-height card pass `config.bars.fitToHeight: true`, and `config.maxCategoryLabelWidth` when labels are long. A `BarList` is usually the better choice for that case.
- Mark a comparison or forecast series with `stroke: { pattern: [4, 4] }`.
