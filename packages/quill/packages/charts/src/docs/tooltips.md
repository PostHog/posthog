# Tooltips

Prefer each chart's built-in tooltip before supplying a `tooltip` render prop.
This guide covers the shared `DefaultTooltip` used by line, bar, and combo charts.
Other charts, such as scatter and pie, provide specialized tooltips; check their props and [chart-type docs](./chart-types.md) for supported options.

## Behavior: `config.tooltip`

`TooltipConfig` (see the JSDoc in `core/types.ts`) sets `enabled`, `pinnable`, `placement`, `resolveClickToNearestSeries`, and `hitArea`.

- `placement: 'cursor'` is the library default through `DEFAULT_CHART_CONFIG`; `follow-data` tracks the highest point at the hovered x and `top` pins the panel to the top edge.
- `pinnable` lets a click pin the panel. An unpinned tooltip is `pointer-events: none`, so row clicks only land once it is pinned.
- `resolveClickToNearestSeries` (default false) makes a click on a pinnable multi-series chart resolve the series nearest the cursor and fire `onPointClick` directly instead of pinning first. Use it only where the target series is visually unambiguous by position (funnel breakdown areas, one per breakdown value). Leave it off where series overlap and a wrong guess is costly (trend lines).
- `hitArea` applies to bar charts. `bar` (default) needs the cursor over the painted bar, so the empty space above a short bar shows nothing. `band` accepts anywhere in the hovered band. `Sparkline` uses `band` because a sparkline bar can be one pixel tall and a zero bucket has no bar to aim at.

## Formatting without a render prop

`config.tooltip` also forwards `valueFormatter`, `labelFormatter`, `showTotal`, `totalLabel`, `totalFormatter`, and `sortedByValue` into `DefaultTooltip`.
Prefer this for "format each row" and "add a total" cases (SQL insights pass per-column formatters this way).
A render prop, if given, owns the content and these fields are ignored.

## `DefaultTooltip` props

Usable from a custom `tooltip` render prop by spreading the context: `<DefaultTooltip {...ctx} footer="..." />`.

- `valueFormatter(value, entry)` gets the row's `seriesData` entry as the second argument, so each row can format with its own `series.meta` (per-column currency or duration). It may return a node, not only a string. A formatter that takes only `value` stays compatible. Defaults to `toLocaleString`.
- `labelFormatter(label)` transforms the raw x-axis label in the header. On time-series charts with `xAxis.timezone` and `interval` set, it defaults to an interval-aware date formatter that includes the weekday for single-day buckets ("Sat, Jun 6, 2026", "Sat, Jun 6, 14:00"); week and month buckets span days, so "Jun 1, 2026", "Jun 2026". An explicit `labelFormatter` still wins.
- `labelRenderer(entry)` overrides how each row's label renders (default: the series label). Use it for richer labels such as breakdown-value pills. Rows share one grid (swatch, label, value), so a renderer that pushes part of its label right lines up as a column down the tooltip.
- `showHeader` (default true) toggles the header row. Pass false where there is no meaningful header (pie slices, aggregated single-column bars).
- `showTotal` appends a row summing the visible series. It excludes `overlay` series (goal lines) and series with `visibility.total: false` (a percentage column beside counts; the row itself still renders), and is suppressed when fewer than two summable series remain. `totalFormatter` defaults to `valueFormatter` applied with the first summable row's entry; `totalLabel` defaults to `'Total'`.
- `sortedByValue` sorts rows by value descending.
- `hideZeroRows` drops rows whose value is exactly `0` (lifecycle statuses absent for a period).
- `onRowClick(entry)` makes each row clickable. The tooltip must be pinned for clicks to land. Use it for a per-series drill-down (the persons modal).
- `footer` renders arbitrary content below all rows, after a divider. Useful for "click to inspect" hints.

Pinned tooltips are copy-friendly.
Outside dismissal keys off where the press started (pointer-down outside the tooltip or chart, or Escape), so a text-selection drag that releases outside the tooltip does not dismiss it, and a click that completes a selection inside a row does not fire `onRowClick`.

## Custom tooltip pieces

A render prop that is not a list of series rows composes the exported pieces so it keeps the built-in look:

- `TooltipSurface` is the floating panel.
- `TooltipSwatch` is the series-color dot.
- `TooltipFooter` is the divider plus muted row, the same slot `DefaultTooltip.footer` renders into.

## Reading `TooltipContext`

- `seriesData` holds one entry per visible series at `dataIndex`, in declaration order. Series with `visibility.tooltip: false` are absent. Look rows up by `entry.series.key`, not by position.
- `BarChart` sets `hoveredSeriesKey`: the bar or segment under the cursor (stacked: the visible segment; grouped: the band-slot hit). A tooltip that describes a single segment (a funnel breakdown) must select by it, not by `seriesData[0]`. It may reference a series hidden from `seriesData` via `visibility.tooltip: false` (a drop-off filler), and is `undefined` on other chart types and on pinned rebuilds without a cursor.
- Grouped layouts also set `inTrackArea`: `true` when the cursor is in the hovered bar's band slot but beyond its filled extent. It is measured on the same laid-out rects as click routing (`minBarSize` flooring included), so a tooltip's converted or drop-off framing always matches what a click at that position resolves to.
- In percent layouts, `value` is a 0..1 fraction.
- `onUnpin` is present only while pinned. Call it before opening a modal from a row click.

## Touch

Cartesian charts are tap-driven on touch devices.
A tap on a data point reveals its tooltip, pinned when `config.tooltip.pinnable`, so its rows are tappable for `onRowClick` drill-downs.
A tap on a different point moves it there.
A tap on the point whose tooltip is already showing runs the click action: dismiss a pinned tooltip, or fire `onPointClick` on non-pinnable charts.
Tapping outside the chart, scrolling, or Escape dismisses.
Mouse hover and click behavior is unchanged; the split lives in `useChartInteraction`, keyed off the pointerdown's `pointerType`.

## Testing

For a chart mounted through `renderHogChart`, `chart.waitForTooltip()` returns a structured `TooltipSnapshot`.
For a chart rendered anywhere else (a product scene), read the tooltip from the DOM: `getHogChartTooltip()` and `waitForHogChartTooltip()` return the portal element, and `createHogChartTooltip(el)` wraps it as `{ element, isPinned }`.
`createDefaultTooltipAccessor(el)` reads a rendered `DefaultTooltip` through its `data-attr="hog-chart-tooltip-*"` hooks: `label()`, `rows()`, `value(seriesLabel)`, `swatchColors()`, `total()`.
Those attributes are a testing contract; keep the accessor and the component in sync.
All helpers come from `@posthog/quill-charts/testing`.
