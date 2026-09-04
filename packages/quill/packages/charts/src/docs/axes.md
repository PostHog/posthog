# Axes, scales, and chrome

Field-level semantics live on `XAxisConfig` and `YAxisConfig` in `utils/use-axis-formatters.ts`, `ChartConfig` and `ValueDomain` in `core/types.ts`, and `YFormatterConfig` in `utils/y-formatters.ts`.
This page covers the behavior that spans several fields.

## Defaults

`useChartTheme()` and `themeFromCssVars()` carry the default styling: a faint dashed grid, a stronger axis line, and a dashed crosshair, each mixed as a share of the host's `--foreground` so they flip with light and dark.
A host with its own token reader can layer just that part via `themeDefaultsFromCssVars()`.

The matching config switches are the library default through `DEFAULT_CHART_CONFIG`: grid, axis lines, tick marks, crosshair, monotone curve, rounded bars, and cursor-anchored tooltip.
`LineChart`, `BarChart`, `ComboChart`, and their time-series variants layer it under `config` via `applyChartDefaults`, so a consumer opts out field by field (`showGrid: false`).
The nested `tooltip` merges key by key, so setting one field keeps `placement: 'cursor'`.
`ScatterChart` renders the same chrome from its own inline defaults.
`Sparkline` and `MetricCard` build their own chromeless config.

## Grid, axis lines, tick marks

- `showGrid` draws grid lines on every chart, including the time-series wrappers. Grid lines always align to the primary (left) y-axis ticks. A `showGrid` on the primary `yAxis` config wins; on secondary axes it is ignored, because two grids with unaligned ticks would be noise.
- `showAxisLines` draws the L-axis alongside the grid, which then skips its own frame and category lines. A right-positioned y-axis gets its own right axis line. `{ x, y }` toggles each edge independently. With axis lines on, line strokes are trimmed at the y-axis and floored onto the x-axis so they rest against the axis instead of straddling it.
- `showTickMarks` draws short canvas tick marks snapped to the same pixel grid as the axis.
- `curve: 'monotone'` smooths line and area series through every point without overshoot.

Theme-side restyle knobs, all optional: `theme.axisLineColor` strokes the baselines and tick marks without changing tick-label color (falls back `axisColor`, then `gridColor`); `theme.gridDashPattern` and `theme.crosshairDashPattern` (`[3, 3]`) dash the interior grid lines and the hover crosshair, while plot-edge frame strokes stay solid.

## X-axis

- Labels must be unique. The x-scale keys positions off the strings, so a duplicate collapses onto the first occurrence and draws the series backwards. On time-series charts pass ISO date strings, never formatted display labels that repeat across years, and format ticks via `xAxis.timezone` and `interval` or `tickFormatter`.
- `xAxis.tickLabelRotation` (`-45` tilts left) fixes the rotation, clamped to `-90..90`. Omit it to keep horizontal labels and the collision behavior.
- `maxCategoryLabelWidth` truncates category labels with an ellipsis and reveals the full value on hover. It also clamps the axis margin, so a long label cannot push the plot off screen. `MAX_CATEGORY_LABEL_WIDTH` is the exported default.

## Y-axis format

`format`: `numeric | short | percentage | percentage_scaled | currency | duration | duration_ms | duration_ns`, plus `prefix` and `suffix`.

Without a `format` or `tickFormatter`, the axis uses the fewest uniform decimal places that keep its ticks distinct.
Numeric and percentage formats default to two decimals but gain a decimal per leading zero below 0.1, so a small-valued axis (latency in seconds over 0..0.012) does not render every tick as `0.01`.
`decimalPlaces` pins the precision.
The duration formats keep three significant digits below a minute, then switch to the `1m 30s` breakdown.
Duration formatters accept seconds (`duration`), milliseconds (`duration_ms`), or nanoseconds (`duration_ns`).

## Baseline and range

- The y-axis clamps a non-negative axis down to 0 by default. To float it to the data range, set `yAxis.startAtZero: false` on `TimeSeriesLineChart`, or `config.floatBaseline: true` on the lower-level `LineChart`. Ignored on a log scale and applied to the primary axis only. Bar charts always draw from zero.
- `yAxis.min` and `max` pin either end on `TimeSeriesLineChart` (`config.valueDomain: { min, max }` on `LineChart`, the same option that carries `include`). Both set pins the axis: skips `nice()`, discards `include`, overrides percent layout. One set clamps that end and leaves the other automatic; it runs after `include` folding, the zero clamp, and `nice()`, so only the extreme label is the raw bound while interior ticks stay round. A single clamp is ignored under a percent layout, where the domain is already 0..1.
- On a log scale a non-positive bound is dropped. A non-finite bound counts as unset, so `{ min: 0, max: Math.max(...[]) }` floors at zero rather than collapsing. An inverted `min >= max` pair falls back to the automatic domain rather than swapping.
- Overlays positioned off the value scale hide themselves outside a bounded window rather than painting over the chrome: a goal line drops out, and so does the value label of a clipped point. A point sitting exactly on the bound keeps its label.
- Bar and combo charts ignore `min` and `max` even though they take the same `yAxis` config. A bar encodes magnitude as length from zero, so a bounded baseline misreads it: 10 vs 11 would draw as 1 vs 2. Pin `valueDomain` there instead, which rescales the bars rather than truncating them. `TimeSeriesBarChart` takes `config.valueDomain`; setting both `min` and `max` skips `nice()` and wins over the goal-line stretch. Pin `{ min: 0, max: dataMax }` so the tallest bar reaches the plot top on an axis-less volume chart, where nice-rounded headroom is invisible waste. `include` merges with the goal-line stretch (`mergeValueDomains` in `utils/goal-lines.ts`).

## Multiple y-axes

Give a series a `yAxisId` to scale it against a second axis.
On the time-series charts, pass `config.yAxis` as an array, one `YAxisConfig` per axis: `id` (matches `Series.yAxisId`; the first entry defaults to `'left'`), `position` (the first entry defaults to `'left'`, the rest to `'right'`), and the usual `scale`, `format`, `tickFormatter`, `label`, `showGrid`, `hide`, `startAtZero`, `min`, `max` per entry.
A single object stays single-axis.

- The second axis only renders when a series targets it; the primary axis owns the grid lines.
- Bar-series axes keep their zero baseline.
- Pin `min` and `max` on a secondary axis whose meaning fixes its range (a 0..1 probability, a 0..100 percentage) rather than letting it float to its data. Otherwise a reference line above every point on that axis falls outside the plot and does not draw. On the primary axis the same bounds arrive as the chart-level `valueDomain`, merged with the goal-line stretch, so they compose rather than override.
- More than two axes work (trends `showMultipleYAxes`): they stack outward per side and alternate sides.
- Each entry's `label` renders that axis's title at its own gutter, driven by the shared `computeYAxisGutters` layout that `AxisLabels` (ticks) and `AxisTitles` (titles) both read, so the two cannot drift. A sole axis pinned `right` renders on the right on every chart type.

## Margins and sizing

- Charts fill their container and need a parent with real dimensions. A zero-height flex child renders nothing. Give the wrapper an explicit height (`h-64`, or `flex-1` in a sized column). `Sparkline` alone takes `height` and `width` props.
- `ChartConfig.margins` overrides only the sides it sets. A side left `undefined` keeps the computed margin, so an object built conditionally (`{ top: reserveOrUndefined }`) is safe. `SlopeChart` merges consumer margins over its computed label gutters with the same rule (`applyMarginOverride`). Pass a module-level constant.

## When the plot is blank

Overlays (axis labels, titles, reference lines, value labels, legend, tooltip) are DOM positioned from the scales; the grid, axis lines, tick marks, and the series are canvas.
If the labels and goal lines render in the right places but the plot area is empty, the layout is fine and the canvas alone failed.

Check the cheap causes first: `theme.skipDraw` suppresses all canvas painting by design (use it for deterministic visual-snapshot tests, where the async paint pipeline races the screenshot), and a `drawStatic` that throws leaves the frame it was clearing empty.
Beyond those, the bitmap is discarded either by `syncCanvasSize` reallocating it (a real resize) or by the browser losing the 2D context, and `useChartCanvas` repaints after both.
A blank plot under correct overlays means one of those paths did not schedule its repaint.
Safari never fires `contextrestored`, so a context lost there stays blank.
