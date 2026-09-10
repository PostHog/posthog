# Legend

Every multi-series chart (`LineChart`, `BarChart`, `TimeSeriesLineChart`, `TimeSeriesBarChart`, `TimeSeriesComboChart`, `SlopeChart`, `PieChart`) takes `config.legend: ChartLegendConfig`.
Hidden by default; `show: true` renders the built-in legend.
The fields are documented on `ChartLegendConfig` in `core/types.ts`.

## Click model

With `interactive` (the default when shown), the legend follows Grafana's model:

- **A plain click isolates that series.** Every other row is hidden (no draw, no scale contribution, no tooltip, so the axes rescale into the freed space) while staying listed but dimmed. Clicking the isolated row again restores all.
- **⌘/Ctrl-click or Shift-click toggles one series** in or out of the visible set, so a selection is built up a row at a time.

Picking one series out of twenty is the common case, and it costs one click rather than nineteen.
A legend with one visibility group has nothing to isolate, so a plain click toggles instead.
On a coarse pointer (touch) there is no modifier key, so a plain tap toggles, and isolate stays reachable through the row menu.

Set `interactive: false` for a static legend.

## Controlled and uncontrolled

By default the chart owns the toggled-off state.
Pass `hiddenKeys` plus `onToggleSeries` to control it yourself.
A controlled legend must also pass `onSetHiddenSeries(nextHiddenKeys)` for isolating and hide-all to work: they replace the whole hidden set at once, which the per-key `onToggleSeries` cannot express in one update.
Without it a controlled legend degrades to plain toggling.

`hiddenKeys` stays in row space either way.

## Visibility groups

`visibilityGroupKey(rowKey)` maps a row onto the identity its visibility is stored against.
Rows sharing a group share one visibility bit: isolating keeps the whole group visible, "only this one is visible" is judged per group, and the group count decides `canIsolate`.
It defaults to the row's own key, so a legend whose rows are independent needs nothing.

Trends needs it because comparing to the previous period puts a series' current and previous rows on one `resultCustomizations` key.
Without the hint the library would isolate a row, correctly leave its twin visible, and then never recognize the result as isolated, so the second click could not restore.

## Row rendering

`renderItem(defaultNode, item, controls)` wraps each rendered row.
Return `defaultNode` to leave a row untouched, or wrap it (a right-click context menu) while keeping the default swatch, label, and toggle rendering.
`controls` is that row's `LegendItemControls`: state (`isHidden`, `isOnlyVisible`, `areAllVisible`, `canIsolate`) plus the actions (`toggle`, `isolate`, `toggleAll`) running the same paths as the clicks, so a row menu never re-derives visibility.

"All" and "the others" mean the legend's rows, not `series`.
Derived overlays (confidence bands, trend lines, moving averages) have no row and are never isolated against.
On time-series charts the legend lists the user's series only, and hiding a series also hides everything derived from it, so no orphaned overlay floats over the gap.

## Layout

- The legend slot in `ChartLegendLayout` is bounded and scrolls. A top or bottom legend caps at about 40% of the chart height; a left or right legend stretches to full chart height and caps at 45% width but never more than 240px. A many-series legend scrolls instead of squeezing the plot.
- The top and bottom cap is a percentage, so it only resolves when the chart container has an explicit `height`. A flex-derived size (`flex: 1` with only `min-height`) does not count and the cap silently no-ops. Pin a real `height` on the container.
- A left or right legend uses `align-self: stretch`, which resolves against the container's used height, so it works without an explicit `height`.
- Long labels clip with an ellipsis only when they run out of available space. A vertical legend truncates at the column edge. A horizontal legend caps each row at an equal share of the line floored at 180px, because flexbox wraps before it shrinks and one long label would otherwise take a whole line. The full text is always in a native `title` tooltip.
- `LegendItem.secondaryLabel` shows muted trailing text (a slope chart's per-series change).

## Lower-level primitives

`Legend` (and `ChartLegend` for layout) is the presentational primitive: pass `items`, `onItemClick`, `hiddenKeys`; filtering series is the caller's state.
`onItemClick(key, { additive })` reports whether the click carried a modifier; deciding what each gesture means is the caller's job.
Use it directly when `config.legend` cannot express what you need (custom item order or labels, the legend rendered outside the chart slot).

`useChartLegend(series, theme, config, items?)` is the shared hook the charts use.
It returns `visibleSeries` (hidden applied as `visibility.excluded`) plus `legendProps` to spread onto `<ChartLegend>`.
`applyHiddenSeries` is the underlying helper, and `legendItemsFromSeries(series, theme)` builds the item list.
