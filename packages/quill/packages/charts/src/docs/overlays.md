# Overlays

Overlays are React DOM (or SVG) rendered on top of the canvas, positioned from the chart's scales.
They compose as children of a chart:

```tsx
<TimeSeriesLineChart series={series} labels={isoLabels} theme={theme} config={config}>
  <ReferenceLine value={100} orientation="horizontal" variant="goal" label="Target" />
  <ValueLabels mode="stack-total" offset={8} />
</TimeSeriesLineChart>
```

Trend lines, moving averages, and confidence bands are not overlays.
They are derived `Series` entries (`overlay: true` for the first two), so the legend, the tooltip, and the axis already know about them.

## Built-in overlays

Prop docs live on each component's props interface under `overlays/`.

### `ReferenceLine` / `ReferenceLines`

Variants: `goal` (dashed grey), `alert` (dashed red), `marker` (solid thin).
A numeric line reveals its value on hover of the line itself (via a wider invisible hit area) or of its label, appended as `label: value` when it has a label and shown alone when it does not.
`showValueOnHover: false` turns that off and removes the hit area, for a line whose caption already states the number or that should not react to the pointer.
A vertical line resolves x through `scales.x(label)`, so it can only sit on a label.
`axisOrientation: 'horizontal'` flips a numeric line into a vertical stripe for horizontal bar charts; it defaults from context, so callers rarely pass it.
A line whose value falls outside a pinned axis range hides itself.

Time-series charts also take `config.goalLines: GoalLineConfig[]`, which builds these lines for you and stretches the value axis so an off-scale target stays on the plot.
`buildGoalLineReferenceLines` is the helper behind it.

### `ValueLabels`

The formatter gets `(value, seriesIndex, dataIndex, context)`.
In percent layouts `value` is a 0..1 fraction; `context.rawValue` holds the original.
`context.bandValues` is the stack's values at this index and `context.previousBandValues` the same for the preceding index (empty at the first), so a formatter can compute a segment's share of the current or the previous band.
`mode="stack-total"` labels only the stack top.
`series.visibility.valueLabel: false` skips a series.
On the time-series charts, prefer `config.valueLabels` so the chart sizes its margins for the labels.

### `AxisTitles`

Renders axis titles in the gutters computed by `computeYAxisGutters`.
The time-series charts render it from `xAxis.label` and `yAxis.label`; compose it yourself only on the base charts.

### `TrendLineOverlay`

Regression lines on vertical bar and combo charts. See [bars.md](./bars.md).

### `HighlightedRange`

A translucent box spanning an x-axis range.
Pass `start` and `end` as data indices or labels, straight from `onDateRangeZoom`'s `startIndex` and `endIndex`.
Use it to mirror an external selection (the rows visible in a paired virtualized list, a picked time window) onto the chart.
On band (bar) charts the box covers the endpoints' full bands; on point (line) charts it runs point to point.
`color`, `fillOpacity`, and `borderOpacity` tune the look (`borderOpacity: 0` drops the edge border).
It clamps to the plot area and renders null when an endpoint does not resolve.

### `AnomalyPointsLayer`

Small filled dots at `{ dataIndex, value, yAxisId, color }`.
DOM rather than a series, because a sparse series would make `drawLine` stitch a line through the `NaN` gaps.
`radius` defaults to 3.

## Custom overlays

Any React child can read layout and hover state through the context hooks:

- `useChartLayout()`: `scales`, `dimensions`, `labels`, `series` (colors resolved), `theme`, `axis` (`orientation`, `xTickFormatter`, `isPercent`), `yGutters`, `resolvePositionValue`, and `canvasBounds()`. Does not re-render on hover.
- `useChartHover()`: `hoverIndex`. Re-renders on every mousemove.
- `useChart()`: both, kept for back-compat. Use the granular hooks unless an overlay needs both.
- `useRadialLayout()` for `PieChart` children: `layout.slices`, radii, `cx`, `cy`.

```tsx
function GoalLine() {
  const { scales, dimensions } = useChartLayout()
  const y = scales.y(100)
  if (y < dimensions.plotTop || y > dimensions.plotTop + dimensions.plotHeight) {
    return null
  }
  return <div data-attr="goal-line" className="absolute left-0 right-0 border-t border-dashed" style={{ top: y }} />
}
```

Rules:

- Position from the scales. `scales.x(label, seriesKey?)` returns the band or point center, or a specific series' bar in grouped layouts. `scales.y(value)` uses the primary axis; `scales.yAxes[id].scale(value)` for another axis. `scales.extent(label)` is the band width on bar charts. `resolvePositionValue(seriesIndex, dataIndex)` is the stacked top when the chart stacks.
- Between-label positions need interpolation between the two bracketing labels. Band and point scales only resolve whole labels.
- `computeVisibleXLabels(labels, scales.x, axis.xTickFormatter)` returns the tick set the axis actually drew, for overlays that must align with it.
- Hide anything outside `dimensions.plotLeft/Top/Width/Height`.
- The overlay layer is `pointer-events: none`. Opt in only on the element the user interacts with.
- An overlay with its own click or hover behavior (a clickable marker) marks its interactive root with `data-hog-charts-interactive-overlay`. It bubbles inside the same wrapper the chart's mousemove tracking listens on, so without the attribute the chart's nearest-point tooltip fights the overlay's own tooltip for the cursor. Stop propagation on click so `onPointClick` does not also fire.
- Give it a `data-attr` and, if it lives in the library, an accessor method in `testing/accessor.ts`.
- Memoize anything derived from `labels` and `scales.x`, keyed on `scales.x` rather than `scales`.

App-specific overlays (annotations, alert thresholds, billing markers) stay in the app next to their consumer.
The library ships only overlays that any host could use.
