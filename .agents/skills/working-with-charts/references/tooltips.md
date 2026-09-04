# Tooltips

Every chart renders the built-in `DefaultTooltip` unless you pass a `tooltip` render prop.
Stay on the built-in tooltip as long as you can.
It already handles the header, the swatch and label grid, per-row formatting, totals, sorting, pinning, row clicks, touch, copy-friendly selection, and the `data-attr` hooks tests read.
A bespoke tooltip has to re-earn every one of those.

## The ladder

Climb only as far as the requirement forces you.

### 1. Behavior only: `config.tooltip`

```ts
tooltip: { pinnable: true, placement: 'cursor' }
```

`TooltipConfig` carries `enabled`, `pinnable`, `placement` (`'cursor'` is the app default via `DEFAULT_CHART_CONFIG`), `resolveClickToNearestSeries`, `hitArea` (bar charts), plus the formatting fields below.
Insight charts share `INSIGHT_TOOLTIP_CONFIG` from `products/product_analytics/frontend/insights/shared/tooltipConfig.ts`.

Set `pinnable: true` whenever a row click has somewhere to go (a persons modal, a drill-down).
An unpinned tooltip has `pointer-events: none`, so rows are only clickable once the user pins it by clicking the chart.
Leave `pinnable` off for a tooltip that is read-only, such as an aggregated bar or a sparkline.

`resolveClickToNearestSeries: true` skips the pin step and fires `onPointClick` for the series under the cursor.
Use it only where the target series is visually unambiguous (one funnel bar per variant), never where lines overlap.

### 2. Formatting only: still `config.tooltip`

```ts
tooltip: {
    pinnable: true,
    valueFormatter: (value, entry) => formatWith(entry.series.meta.settings, value),
    labelFormatter: (label) => formatDate(label),
    sortedByValue: true,
    showTotal: true,
    totalFormatter: formatCount,
}
```

`config.tooltip` forwards `valueFormatter`, `labelFormatter`, `showTotal`, `totalLabel`, `totalFormatter`, and `sortedByValue` into `DefaultTooltip`.
`valueFormatter` gets the row's `seriesData` entry as its second argument, so per-series formatting reads `entry.series.meta` instead of a lookup table.
On time-series charts with `xAxis.timezone` and `interval`, the header already formats the ISO label; only override `labelFormatter` when the default wording is wrong.

SQL insights are the reference for this rung: `buildSqlTooltipConfig` in `frontend/src/queries/nodes/DataVisualization/Components/Charts/sqlLineGraphAdapter.ts`.

### 3. Content the config cannot express: render prop wrapping `DefaultTooltip`

`DefaultTooltip` takes props that `config.tooltip` does not forward: `labelRenderer`, `showHeader`, `hideZeroRows`, `onRowClick`, and `footer`.
When you need one of those, write a render prop that spreads the context into `DefaultTooltip` and adds the prop:

```tsx
const renderTooltip = useCallback(
    (ctx: TooltipContext<MyMeta>) => (
        <DefaultTooltip
            {...ctx}
            valueFormatter={formatValue}
            hideZeroRows
            sortedByValue
            footer="Click to view persons"
        />
    ),
    [formatValue]
)

<TimeSeriesLineChart tooltip={renderTooltip} config={{ tooltip: { pinnable: true } }} />
```

Once a render prop exists it owns the content, so move any formatters you had on `config.tooltip` into the props.
The `config.tooltip` behavior flags (`pinnable`, `placement`) still apply.

`onRowClick` fires with the row's `seriesData` entry.
Call `ctx.onUnpin?.()` before opening a modal from it, or the pinned tooltip floats over the modal.

### 4. Insight series charts: `InsightSeriesTooltip`

Any chart that shows insight results (trends, stickiness, lifecycle, retention, funnel-line) uses `InsightSeriesTooltip` from `products/product_analytics/frontend/insights/shared/InsightSeriesTooltip.tsx`.
It is rung 3 done once: a `DefaultTooltip` wrapper that formats values through the aggregation axis settings, renders breakdown and compare-period labels, adds the series letter when names collide, opens the persons modal from `onRowClick`, and writes the "Click to view people" footer.

Requires `series.meta` shaped like `TrendsSeriesMeta` (`action`, `series_name`, `breakdown_value`, `compare_label`, `days`, `order`, `filter`).
Build it with `buildTrendsSeriesMeta`.

Its escape hatches cover the known variants, so extend it instead of forking it:

| Prop                   | Used by                                                                                 |
| ---------------------- | --------------------------------------------------------------------------------------- |
| `altTitle`             | Stickiness (x is an interval count, not a date)                                         |
| `renderCount`          | Pie (value plus share of total), lifecycle (absolute value of a negative dormant count) |
| `renderSeriesOverride` | Lifecycle (status name instead of event name), retention (cohort prefix)                |
| `showHeader: false`    | Pie slices, aggregated bar value                                                        |
| `sortedByValue: false` | Bars and lifecycle, where the visual stacking order matters more than value order       |
| `hideZeroRows`         | Lifecycle, where a zero means the status is absent                                      |
| `footerOverride`       | A dashboard tile whose click opens the insight instead of the persons modal             |

### 5. A different layout entirely: `TooltipSurface` and friends

When the tooltip is not a list of series rows (a funnel step with converted and dropped counts, a scatter point with x and y, a box plot's five numbers), compose the exported pieces so the panel still looks built in:

- `TooltipSurface` is the floating panel, positioned from the context.
- `TooltipSwatch` is the series color dot.
- `TooltipFooter` is the divider plus muted hint row, the same slot `DefaultTooltip.footer` renders into.

Examples: `products/product_analytics/frontend/insights/funnels/shared/FunnelStepTooltip.tsx`, `products/ai_observability/frontend/clusters/ClusterScatterTooltip.tsx`, `frontend/src/scenes/surveys/components/question-visualizations/questionVizTooltips.tsx`.

Do not hand-roll a `div` with your own shadow and padding.
Do not import the legacy `InsightTooltip` for a new chart.

## Reading the context correctly

- `ctx.seriesData` holds one entry per visible series at `ctx.dataIndex`, in declaration order. Series with `visibility.tooltip: false` are absent. Look rows up by `entry.series.key`, never by array position.
- On stacked and grouped bar charts, `ctx.hoveredSeriesKey` names the segment under the cursor. A tooltip that describes one segment (a funnel breakdown, a stacked bar's slice) selects by it rather than by `seriesData[0]`. It may name a series hidden from `seriesData`, and it is `undefined` on other chart types and on pinned rebuilds.
- `ctx.inTrackArea` is true on grouped bars when the cursor is past the bar's filled extent, so a funnel tooltip can frame the hover as drop-off. It is measured on the same rectangles as click routing, so what the tooltip says and what a click does always agree.
- In percent layouts, `value` is a 0..1 fraction. Format it as a percentage; do not divide again.
- Overlay series (trend lines, moving averages) and series with `visibility.total: false` are excluded from `showTotal`.
- Sparklines and inline strips usually set `tooltip: { enabled: false }` and surface the hovered value elsewhere through `useChartHover()`, so the chart does not paint a panel over a 12px bar.
