# Bars

Applies to `BarChart`, `TimeSeriesBarChart`, `ComboChart`, `TimeSeriesComboChart`, and `FunnelChart`.
Field docs live on `BarChartConfig` and `BarsConfig` in `core/types.ts`; the per-bar `Series` options are on `Series.bars` and `Series.trackData`.

## Layouts

- `barLayout: 'stacked' | 'grouped' | 'percent'`. Percent stacks bar series to 100% and puts the value scale on 0..1, so formatters receive fractions. Stacking groups by axis.
- `axisOrientation: 'horizontal'` for horizontal bars. Drag-to-zoom is disabled there, since the interaction axis is vertical.
- `divergingStack` (stacked only) stacks negative values below the zero baseline instead of clamping them to 0. Same semantics on `ComboChart` and `TimeSeriesComboChart`.
- `barCornerRadius` rounds the end caps. It is a top-level key on every bar-capable chart, including the time-series and combo configs.
- `TimeSeriesBarChart` takes `minBarSize`, `bandPadding`, `margins`, and `maxCategoryLabelWidth` as top-level config keys (alongside `barCornerRadius` and `fillStyle`) rather than under `bars`.

## Per-bar overrides

`Series.bars[i]` overrides `color`, `label`, and `meta` for one bar, so one series can draw bars with distinct identity (an aggregated breakdown, one bar per value) instead of paying the cost of one series per bar.
Bar fill, hover highlight, and the tooltip read it; track decorations do not.

`bars[i].hatch: true` fills that bar with a diagonal-hatch pattern in its resolved color.
Use it to flag individual not-final bars (a bucket still being ingested) at arbitrary indices.
For a contiguous trailing range, `stroke.partial.fromIndex` does the same.

## Minimum bar size

`bars.minBarSize` (px) floors each non-zero bar's thickness along the value axis, so a single-occurrence bucket stays visible beside a spike three orders of magnitude taller.
Zero-valued bars are never floored, so empty buckets stay empty.

On a stacked chart only the outermost segment is floored: flooring an interior one would oversize a rect the segment above overpaints while still capturing its hover and clicks.
A breakdown stack floors only its top segment, so the option is aimed at single-series volume charts and grouped bars.
`Sparkline` does not expose it.

`bars.minBarSizeScope: 'hover'` restricts the floor to the hover highlight and hit-testing.
The static layer draws true sizes and a tiny bar grows to a clickable nub under the cursor; while its track is hovered, the floored bar is also revealed in its plain color.
The default `'always'` floors the static layer too.

## Interactive extent: `trackData`

`Series.trackData[i]` caps a bar's interactive extent at a per-bar ceiling in value units.
The region beyond it is a fully inert gap: no hover, tooltip, pointer cursor, highlight, or click (the chart vetoes the hover via `resolveHoverIndex`).
On grouped charts with `bars.track`, the hatched "share of a whole" track also fills only to the ceiling.
On stacked charts no track is drawn; the ceiling only bounds interactivity.

Funnel compare uses it to draw a shorter period's volume gap as empty space rather than drop-off, in both its grouped (left to right) and stacked (top to bottom) charts.

## Hit-testing

Bar geometry is computed once by `computeSeriesBars` in `core/bar-layout.ts`, and the hover path resolves the bar under the cursor from the same rects (`charts/BarChart/bars-under-cursor.ts`).
A change that lets the hover geometry diverge from the draw geometry is a bug.
`TooltipContext.hoveredSeriesKey` and `inTrackArea` come from this resolution; see [tooltips.md](./tooltips.md).

## Value labels on bars

`ValueLabels` collision avoidance is a single greedy pass over the full 2D label box (`minGap` on every side).
A label is dropped only when it overlaps a higher-priority one, so neighbors at different heights both keep their labels instead of the axis dropping every other bar.
Ties resolve toward earlier series and left to right, top to bottom.
See [overlays.md](./overlays.md) for the formatter contract.

## Trend lines on bars

`TrendLineOverlay` renders linear or exponential regression lines as SVG polylines on vertical bar and combo charts.
Use it via `trendLines?: TrendLineConfig[]` in `TimeSeriesBarChartConfig` or `TimeSeriesComboChartConfig`; the chart computes the derived series via `buildTrendLineSeries` and passes them to the overlay.
Vertical orientation only; it returns null on horizontal charts.
Legend-toggled-off series are filtered automatically.

## Combo charts

`ComboChart` mixes bar, line, and area series on one band x-axis.
Set `Series.type` per series; vertical only.
Under `barLayout: 'percent'`, a line or area series needs its own `yAxisId: 'right'` axis, because one sharing the bars' axis cannot plot raw values against their 0..1 scale.
`ComboChart` honors `valueDomain` (primary axis only) and `showAxisLines`.

`TimeSeriesComboChart` wraps it the way the other time-series charts wrap their base: `config.xAxis` and `config.yAxis` (date tick formatter, y format, scale, grid), `config.goalLines` (off-scale targets stretch the value axis via `valueDomain`), `config.legend`, and `config.valueLabels`.
`barLayout`, `divergingStack`, and right-axis series carry over.
