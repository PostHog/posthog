# Chart types

Behavior notes for the specialized charts.
The line, bar, and combo families are covered by [axes.md](./axes.md), [bars.md](./bars.md), and the README.
Prop-level docs live on each chart's props and config interfaces.

## TimeSeriesLineChart

`LineChart` plus time-series chrome: date ticks from `xAxis.timezone` and `interval`, an interval-aware tooltip header, `goalLines`, `valueLabels`, `legend`, and the derived series configs (`confidenceIntervals`, `movingAverage`, `trendLines`).
`comparisonOf` maps comparison series keys to their primary so they render dimmed.
`percentStackView` renders area series as a 100% stack with a 0..100% axis.

Derived series: trend lines and moving averages are `overlay: true`, so they are excluded from stacking and from the baseline calculation and a projection cannot drag the axis below zero.
Confidence bands are not overlays; they represent real uncertainty whose range should still influence the axis.
Hiding a series through the legend hides everything derived from it.

## ScatterChart

Takes `series: ScatterSeries[]`, each `{ key, label, points: { x, y, label?, radius?, color?, meta? }[], color?, pointRadius?, shape? }`, and no `labels`, since both axes are continuous.

- `config.xAxis` and `config.yAxis` are symmetric `ScatterAxisConfig`s (`scaleType`, `domain`, `label`, `tickFormatter`, `hide`, `startAtZero`). Both axes float to their data range by default, because forcing either to zero squashes the correlation into a corner.
- On a log axis, points with a non-positive coordinate are dropped. A pinned `domain` narrows the chart rather than the viewport: points outside it are dropped too, so nothing piles onto the plot edge at a value it does not have.
- `shape` (`circle | square | triangle | cross`) separates series without relying on color. Markers fill at `config.fillOpacity` (0.7) over an opaque outline so a dense cloud reads as density.
- Hit-testing is 2D and edge-based: the tooltip resolves the marker nearest the cursor in both axes (a large marker the cursor sits inside beats a small one whose center is nearer), and empty plot area resolves to nothing rather than to the nearest column.
- `onPointClick` and the `tooltip` render prop receive the resolved `ScatterPointDatum` (with its series and `meta`), not a data index. `config.tooltip` takes `enabled`, `placement`, `labelFormatter`, `xFormatter`, `yFormatter`. The default tooltip labels its two rows from the axis titles, falling back to the hovered point's series label for y and to `X` for x; a header that would repeat the y row is dropped.
- Chrome toggles are the usual `showGrid`, `showAxisLines`, `showTickMarks`, `showCrosshair`, all on by default. X ticks are resolved once per layout, so grid lines, tick marks, and labels are one set.
- `showBestFit` draws a dashed least-squares line per series, in that series' color, spanning only its own points. It is canvas, not `TrendLineOverlay`, whose regression fits y against the array index and means nothing where x is a measure. The fit runs over pixel positions, so it minimizes the right residuals on both linear and log axes, and it sees only drawn points: a series with fewer than two, or all at one x, gets no line.
- `onAreaSelect` reports the dragged rectangle through the continuous scales; see [interactions.md](./interactions.md).

## FunnelChart

A thin wrapper over grouped `BarChart` that owns the funnel look: hatched `track`, rounded and shadowed bars, percent value axis.

- `steps` is a `string[]` of display labels; duplicates are fine, bands are keyed by step index.
- Each `Series.data[stepIndex]` is the conversion from the first step as a percent (0..100). `funnelFromCounts` builds the single-series case from raw `{ label, count }` steps (a zero basis yields 0, not `NaN`).
- `onStepClick` replaces `onPointClick` and reports `{ stepIndex, converted }`; `converted: false` means the hatched drop-off track above the bar was clicked.
- `stepFooter(stepIndex)` renders per-step content in a row below the plot, pixel-aligned under each step's bars, and hides the built-in step labels. Use it for step legends richer than an axis label.
- Config: `hideStepLabels`, `hideValueAxis`, `barCornerRadius`, `bandPadding`, `minBarSize` (hover and click floor for near-zero bars; default `FUNNEL_MIN_BAR_SIZE` of 4px, applied with `minBarSizeScope: 'hover'` so the resting bar keeps its true size and grows to a clickable nub under the cursor; pass 0 to disable), `maxBandRange` (cluster a two or three step funnel instead of stretching it), `chartMinHeight` (floor the plot height when `stepFooter` is set, so a tall footer cannot starve the canvas to zero height in a height-constrained column), plus the usual `tooltip`, `legend`, `margins`.
- Compare mode uses `trackData` to draw a shorter period's volume gap as empty space; see [bars.md](./bars.md).

## SlopeChart

One line per series from a left "before" to a right "after"; `data` is `[start, end]`.

- `showSeriesLabels` puts the name beside each point; on collision the series with the largest change keeps its label.
- `showStartLabels` and `showEndLabels` are chart-level defaults, overridable per series via `meta.showStartLabel` and `meta.showEndLabel`. The value axis is hidden by default; the start and end labels are the readout.
- `legend: { show, position }`. Rows carry the formatted change and are ordered biggest to smallest by end value to match the lines' right-edge order.
- `valueFormatter` and `deltaFormatter` format the labels and the legend's change.
- The default tooltip orders rows biggest to smallest by the hovered point's value, so many-breakdown tooltips match the lines' vertical order, and formats with `valueFormatter` so values match the on-chart labels' units.
- `meta.incompleteEnd` dashes only the second half of that connector (the last point is the current incomplete period). The renderer splits the final segment at its midpoint via `stroke.partial.fromFraction`, so a two-point line needs no phantom interior point.
- Consumer `margins` merge over the computed label gutters; an `undefined` side keeps the gutter the labels reserved.

## PieChart

Part of whole, one value per series (`data[0]`).

- `innerRadiusRatio` makes a donut; `centerLabel` fills the hole.
- On-slice labels via `showLabelOnSlice` and `showValueOnSlice`, positioned with `labelRadiusRatio` (0 is the center, 1 the rim) and gated by `minSlicePercentForLabel`.
- `sliceValueDisplay` picks what the numeric line holds: `'value'`, `'percent'`, or `'both'` for `352 (18.4%)`. Defaults to `'percent'` when `isPercent` is set, else `'value'`.
- `config.legend` renders the built-in legend; a toggled-off slice is removed and the rest rescale to the full circle.
- `theme.backgroundColor` is required for the hover pop-out mask; without it the pop-out is skipped. `disableHoverOffset` turns the pop-out off.
- Children read `useRadialLayout()` for `layout.slices`, `innerRadius`, `outerRadius`, `cx`, `cy`, and `centroidAngle`.

## BoxPlot

Distribution summaries: `{ min, p25, median, mean, p75, max }` per label.
Supports `config.legend` for grouped series and `onBoxClick`.
`axisOrientation: 'horizontal'` lists the labels down the y-axis and draws values along x; `yScaleType: 'log'` then applies to that x value axis, and `yTickFormatter` formats its ticks.
The tooltip receives a `BoxPlotTooltipContext`; `BoxPlotTooltip` is the default.

## Heatmap

A 2D density grid: `xLabels` by `yLabels` (row 0 at the bottom), `cells[row][col]` counts mapped to color intensity on one accent.
Log ramp by default; `colorScale: 'linear'` to opt out.
A single-cell tooltip resolves from the cursor, `onCellClick` reports `{ xIndex, yIndex, value }`, and `onBrush` reports row and column index ranges.

## SankeyChart

Flow between stages: `nodes: { id, label?, color?, meta? }[]` and `links: { source, target, value, color?, meta? }[]`, where `source` and `target` are node ids.
There is no `series` or `labels`.

- The graph must be acyclic and every link must name existing nodes; the layout throws otherwise, and the chart's error boundary reports it through `onError`.
  A node that recurs at several stages (the same tool called twice) needs one id per stage, so prefix ids with the stage.
- Nodes that share a `label` share a palette color, so a repeated tool keeps one hue across columns.
  A link without `color` takes its source node's color.
  `var(--…)` colors resolve inside the chart.
- `nodeAlign` decides where a flow that ends early sits: `justify` (default) moves terminal nodes to the last column; `left` keeps each node at its own depth, which reads right when columns are stages.
  `preserveNodeOrder` keeps input order within a column instead of untangling ribbons.
  A node with `column` set is pinned there whatever its depth, and the graph grows to fit the highest pin; use it when the data names its own stage, so `columnLabels` stay truthful for flows that end early or start late.
- `columnLabels` renders headers above each column and reserves room for them.
  Node labels are DOM overlays beside each node, truncated to the free space before the next column; the last column's labels sit to its left.
  A label that would print over a larger neighbor's label in the same column is dropped; the tooltip still names that node.
  `showNodeValues` appends the node value.
- Hovering a node lifts its ribbons and dims the rest of the graph; hovering a ribbon lifts just that ribbon.
  The default tooltip shows the node label or `source → target`, the value, and its share of `layout.total` (the summed inflow of the nodes with no incoming link).
  `onNodeClick` and `onLinkClick` receive the laid-out datum with its `meta`.
  `tooltip.placement` takes the cartesian charts' values and defaults to `cursor`.
  On touch, the first tap on a node or ribbon shows its tooltip and a second tap on the same one fires the click handler.
- `onHoverChange` reports the node or ribbon under the cursor, and `null` when it leaves.
  `highlight` takes over emphasis: the chart dims everything outside `{ nodeIds, linkIndices }` and stops its own hover dimming, so a host can light up a whole downstream path or a selection.
  Link indices are positions in the `links` prop; the layout keeps that order.
- Custom overlays read `useSankeyLayout()` for the positioned `nodes`, `links`, `columnX`, and `total`.
  An overlay with its own pointer handling marks its root with `data-hog-charts-interactive-overlay`, which also stops the chart from reporting a hover while the cursor is on it.
- The layout engine ships on its own as `sankeyLayout` (plus the `sankeyLeft` / `sankeyJustify` alignments and `sankeyLinkHorizontal`) for hosts that draw their own SVG.

## Sparkline

An axis-less preset over `LineChart` (default, gradient-filled line) or stacked bars via `type: 'bar'`.
Takes a flat `number[]` plus `color`, or full `series` for multi-series, and `height` and `width` props instead of filling its container.
The tooltip is off by default; opt in with a `tooltip` render prop.
Bars use `hitArea: 'band'`.
`onHoverIndexChange` lets a consumer drive a hover-following headline without subscribing to `useChartHover` itself.
`minBarSize` is not exposed.

## MetricCard

A left-aligned tile: headline number, change pill, sparkline.

- `title={null}` drops the title row. The header band collapses when there is no title and no change pill, and the subtitle row is omitted when there is no subtitle and no `labels`, so a value-only card renders just the number.
- `changeSize="md"` renders a larger pill (default `sm`); `changeInline` puts it beside the headline instead of in the header.
- `sparklineFill` makes the sparkline fill the card's remaining height instead of a fixed `sparklineHeight`; `sparklineDashedFromIndex` dashes it from that index onward (an in-progress trailing period).
- `subtitle` always wins. `restingSubtitle` (`'Avg'`) shows only at rest and yields to the hovered point's label on hover; pair it with a `value` that summarizes the series.
- `hoverChangeFromPreviousPoint` keeps the resting `change` pill at rest but, while hovering, swaps it for the hovered point's change versus the previous point (hidden at the first point).
- `changeTooltip` shows a styled hover tooltip on the change pill, using the host's tooltip surface tokens with chart-surface fallbacks.

The composable form is `Metric` in `@posthog/quill-components` (it needs `Card` and `Badge` from primitives, which charts cannot depend on).
It is built on `Sparkline` plus the headless helpers this package exports: `resolveDelta` and `computeFallbackChangePercent` (delta math), `useAnimatedNumber` (count-up headline), `useHoverIntent` (hover dwell), and the `MetricChange` and `ResolvedDelta` types.
Reach for `Metric` for a custom layout; use `MetricCard` for the default self-contained tile.
