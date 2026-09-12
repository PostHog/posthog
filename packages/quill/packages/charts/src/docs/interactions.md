# Interactions

## `onPointClick`

Fires with `PointClickData` (see `core/types.ts`): the primary `series`, `seriesIndex`, `dataIndex`, `label`, `value`, `crossSeriesData` for every visible series at that index, the `cursor` position, and `inTrackArea` on grouped bars.
Read the domain object back from `series.meta`, not from array position.

On a `pinnable` multi-series chart, a click pins the tooltip first and the user then clicks a row (`DefaultTooltip.onRowClick`).
`config.tooltip.resolveClickToNearestSeries` skips the pin and fires `onPointClick` for the nearest series directly; see [tooltips.md](./tooltips.md) for when that is safe.

Chart-specific variants: `FunnelChart.onStepClick` reports `{ stepIndex, converted }`, where `converted: false` means the hatched drop-off track was clicked; `PieChart.onSliceClick`; `BoxPlot.onBoxClick`; `Heatmap.onCellClick` reports `{ xIndex, yIndex, value }`; `ScatterChart.onPointClick` receives the resolved `ScatterPointDatum`.

## Marking which points are clickable: `isPointClickable`

On `BarChart`, `TimeSeriesBarChart`, and the base `Chart`.
`onPointClick` alone makes every point actionable, so the pointer cursor covers the whole plot and hides the drag crosshair.
`isPointClickable(dataIndex)` says which points the handler acts on, so the pointer cannot promise an action that never fires.
Omit it to leave every point actionable, which is what every chart that does not pass it does.

- The pointer appears only on an accepted point. The rest keep the crosshair, or the default cursor when the chart has no drag gesture.
- `onPointClick` does not fire for a rejected point, so the handler no longer needs its own index guard.
- It resolves per data index, not per bar in a stack. One cursor and one click address a column, so a rejected index suppresses every series in it, including the per-bar routing `wrapClickData` would otherwise apply.
- It bounds the click only. Hover, highlight, and tooltip still work on a rejected point, which is what separates it from `trackData`, which makes the region inert altogether.
- A rejected column on a `pinnable` chart still pins its tooltip. The pointer says the point is actionable, not that this click fires the handler: a pinnable multi-series chart pins on the first click and drills in from a tooltip row, accepted or not.
- The predicate is read live rather than captured, so it does not have to be memoized. It is called only with an index inside `labels`, so it can read its own data by index without a bounds check.

## Drag-to-zoom: `onDateRangeZoom`

On `LineChart`, `TimeSeriesLineChart`, `BarChart`, `TimeSeriesBarChart`, and the base `Chart`.
The user drags horizontally and the callback fires once with `{ startLabel, endLabel, startIndex, endIndex }`.
The chart does not manage zoom state; the parent decides what to do with the range, usually updating a date filter.

- Despite the name it is label-generic: it resolves the drag against label positions, so it works on categorical labels (weekdays, duration buckets) as on dates.
- A drag whose edges both snap to the same label (common on sparse charts, a three-bar monthly chart) selects that single bucket, provided the drag spans enough distance to read as intentional.
- The cursor switches to a crosshair when set, except over an actionable point, where it stays a pointer. A plain click without movement still pins the tooltip or fires `onPointClick`.
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

## Legend clicks

Plain click isolates, modifier click toggles, tap toggles.
See [legend.md](./legend.md).

## Testing interactions

`hoverAtIndex`, `clickAtIndex`, `hoverUntilTooltip`, and `dragSelection` from `@posthog/quill-charts/testing` drive these gestures in jsdom.
`hoverUntilTooltip` and `clickAtIndex` re-dispatch until the tooltip portal mounts, because the chart drops events fired before it commits its scales.
Both default to a 3000ms budget.
Pass an explicit `timeout` whenever the call sits behind another wait in the same test; two full-length waits chained together exceed Jest's 5000ms per-test budget, so give the pair one shared deadline.
See [TESTING.md](./TESTING.md).
