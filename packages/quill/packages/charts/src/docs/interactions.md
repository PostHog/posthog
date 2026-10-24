# Interactions

## `onPointClick`

Fires with `PointClickData` (see `core/types.ts`): the primary `series`, `seriesIndex`, `dataIndex`, `label`, `value`, `crossSeriesData` for every visible series at that index, the `cursor` position, and `inTrackArea` on grouped bars.
Read the domain object back from `series.meta`, not from array position.

On a `pinnable` multi-series chart, a click pins the tooltip first and the user then clicks a row (`DefaultTooltip.onRowClick`).
`config.tooltip.resolveClickToNearestSeries` skips the pin and fires `onPointClick` for the nearest series directly; see [tooltips.md](./tooltips.md) for when that is safe.

`isPointClickable(dataIndex)` (on `BarChart`, `TimeSeriesBarChart`, and the base `Chart`) limits `onPointClick` and the pointer cursor to some points.
Other points keep hover and tooltip, and show the drag crosshair if the chart has one.

Chart-specific variants: `FunnelChart.onStepClick` reports `{ stepIndex, converted }`, where `converted: false` means the hatched drop-off track was clicked; `PieChart.onSliceClick`; `BoxPlot.onBoxClick`; `Heatmap.onCellClick` reports `{ xIndex, yIndex, value }`; `ScatterChart.onPointClick` receives the resolved `ScatterPointDatum`.

## Drag-to-zoom: `onDateRangeZoom`

On `LineChart`, `TimeSeriesLineChart`, `BarChart`, `TimeSeriesBarChart`, and the base `Chart`.
The user drags horizontally and the callback fires once with `{ startLabel, endLabel, startIndex, endIndex }`.
The chart does not manage zoom state; the parent decides what to do with the range, usually updating a date filter.

- Despite the name it is label-generic: it resolves the drag against label positions, so it works on categorical labels (weekdays, duration buckets) as on dates.
- A drag whose edges both snap to the same label (common on sparse charts, a three-bar monthly chart) selects that single bucket, provided the drag spans enough distance to read as intentional.
- The cursor switches to a crosshair when set, except over a clickable point, where it stays a pointer. A plain click without movement still pins the tooltip or fires `onPointClick`.
- X-axis only. No effect on charts with a vertical interaction axis (`axisOrientation: 'horizontal'` bars), where the core disables the gesture.
- Both emitted values are bucket starts. Widening the end to the last bucket's end is the host's job.

`HighlightedRange` takes the same indices to draw the selection back onto the chart.

## 2D brush: `onAreaSelect`

On the base `Chart`, for chart-type adapters.
The drag tracks both axes, the selection rect clamps to the dragged vertical range, and the completed gesture reports the x label range plus the raw x and y pixel spans with the committed scales, so the adapter maps pixels onto its own bands.
Each edge is clamped to its axis first, so a drag that overshoots the plot reports the rectangle the user saw rather than an extrapolated one.
Takes precedence over `onDateRangeZoom` when both are set.

- `Heatmap` exposes it as `onBrush` with row and column index ranges; a near-horizontal drag (under 8px vertical) spans every row.
- `ScatterChart` exposes it as its own `onAreaSelect`, inverting the pixel spans through its continuous scales. The label range is meaningless there.

## Hover and touch

Hover state lives in its own context so only `useChartHover()` consumers re-render on mousemove.
Anything that needs layout only reads `useChartLayout()`.
Touch devices are tap-driven; see [tooltips.md](./tooltips.md).

## Chart groups

`ChartGroup` links the charts inside it, at any depth, so a dashboard reads as one surface.
Hovering one chart shows the same moment on every other chart.
It renders no DOM, so wrap whatever grid you already have.

```tsx
const [range, setRange] = useState<ChartGroupRange | null>(null)

<ChartGroup onZoom={setRange}>
  <TimeSeriesLineChart series={latency} labels={minuteLabels} theme={theme} />
  <TimeSeriesBarChart series={errors} labels={fiveMinuteLabels} theme={theme} />
  <Heatmap xLabels={tenMinuteLabels} yLabels={durationBuckets} cells={cells} theme={theme} onBrush={onBrush} />
  <MetricCard title="Requests" data={requests} labels={quarterHourLabels} theme={theme} />
</ChartGroup>
```

| Prop                              | Default     | Behavior                                                                                                                                            |
| --------------------------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `syncCrosshair`                   | `true`      | The other charts draw a crosshair and their hover highlight at the matching x.                                                                      |
| `syncTooltip`                     | `'hovered'` | `'all'` also opens each other chart's tooltip at the matching x.                                                                                    |
| `onZoom`                          | none        | Turns drag-to-zoom on for every time chart and fires once per drag with a `ChartGroupRange`. The group zooms nothing: pass the new range back down. |
| `syncSelection`                   | `true`      | A completed brush (the Heatmap's `onBrush`) shows as a `HighlightedRange` on every chart. Escape clears it.                                         |
| `selection` / `onSelectionChange` | none        | Control the shared selection from the parent. Leave `selection` undefined to let the group keep it.                                                 |

### How charts match

Charts match by x value, not by index, so each chart keeps its own labels and interval.

- **ISO time labels** (`2024-05-01`, `2024-05-01T10:05:00Z`) match by time. A label marks the start of its bucket, and the hovered time maps to the bucket that contains it, so 10:07 on a 1-minute chart lands on the 10:05 bar of a 5-minute chart. A time before the first bucket, after the last one, or inside a gap in the labels matches nothing, and that chart shows no hover. A label without an offset reads as UTC.
- **Other labels** match by exact string, so two weekday charts line up and a weekday chart never lines up with a time chart.
- **No comparable x**: `PieChart`, `ProportionBar`, `BarList`, `StackedBarList`, `FunnelChart`, `SlopeChart`, `SankeyChart`, and `ScatterChart` never join. A `Sparkline` or `MetricCard` joins only when it has `labels`, because its index labels line up with nothing.

`ChartGroupRange` carries both `startLabel` / `endLabel` from the chart the user dragged, and `from` / `to` in epoch milliseconds on time axes, where `to` is the end of the last bucket.
Filter every chart's data by `[from, to)` rather than by label, because each chart has its own buckets.

### Behavior worth knowing

- Pinning a tooltip pins it on that chart only. Moving the pointer off a chart clears the hover on every chart, pinned or not.
- A chart mounted while another is hovered picks up the hover at once. A hovered chart that unmounts clears it.
- Hover reaches the other charts through a store outside React: each one repaints only its hover canvas, and no chart re-renders or repaints its static canvas. `syncTooltip: 'all'` re-renders one tooltip per chart for each hovered label, so it costs more.
- `useChartHover()` reports this chart's own pointer hover only. A custom chart type sees a mirrored hover in `drawHover` as `hoverSource: 'group'` with a null `hoverPosition`, so it can highlight the whole column. `BoxPlot` draws only the crosshair there.
- `MetricCard` follows the group hover with its headline and subtitle, after its `hoverIntentMs` dwell. `useChartGroupHoverIndex(labels)` gives the same index to your own DOM.
- A mirrored line chart rings each series at the matching x, up to 12 series. Past that it draws only the crosshair.

### Opting out

Pass `syncWithGroup={false}` to any chart to keep it out of the enclosing group: it neither shares its hover, zoom, and selection nor mirrors the others'.

## Legend clicks

Plain click isolates, modifier click toggles, tap toggles.
See [legend.md](./legend.md).

## Testing interactions

`hoverAtIndex`, `clickAtIndex`, `hoverUntilTooltip`, and `dragSelection` from `@posthog/quill-charts/testing` drive these gestures in jsdom.
`hoverUntilTooltip` and `clickAtIndex` re-dispatch until the tooltip portal mounts, because the chart drops events fired before it commits its scales.
Both default to a 3000ms budget.
Pass an explicit `timeout` whenever the call sits behind another wait in the same test; two full-length waits chained together exceed Jest's 5000ms per-test budget, so give the pair one shared deadline.
See [TESTING.md](./TESTING.md).
