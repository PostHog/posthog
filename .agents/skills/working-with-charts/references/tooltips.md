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

Insight charts share `INSIGHT_TOOLTIP_CONFIG` from `products/product_analytics/frontend/insights/shared/tooltipConfig.ts`.
Set `pinnable: true` whenever a row click has somewhere to go (a persons modal, a drill-down), and leave it off for a read-only tooltip such as an aggregated bar or a sparkline.
The fields (`enabled`, `pinnable`, `placement`, `resolveClickToNearestSeries`, `hitArea`) and when each is safe are in the library's [docs/tooltips.md](../../../../packages/quill/packages/charts/src/docs/tooltips.md).

### 2. Formatting only: still `config.tooltip`

`config.tooltip` also forwards `valueFormatter`, `labelFormatter`, `showTotal`, `totalLabel`, `totalFormatter`, and `sortedByValue` into `DefaultTooltip`, so per-row formatting needs no render prop.
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

Once a render prop exists it owns the content, so move any formatters you had on `config.tooltip` into the props; the behavior flags (`pinnable`, `placement`) still apply.
Each prop's semantics are in the library's [docs/tooltips.md](../../../../packages/quill/packages/charts/src/docs/tooltips.md).

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

## Reading the context

`seriesData`, `hoveredSeriesKey`, `inTrackArea`, percent-layout fractions, and `onUnpin` are documented in the library's [docs/tooltips.md](../../../../packages/quill/packages/charts/src/docs/tooltips.md) under "Reading `TooltipContext`", and the charts `AGENTS.md` gotchas list the ones that bite.
One app habit on top: sparklines and inline strips set `tooltip: { enabled: false }` and surface the hovered value in a sibling element through `useChartHover()`, so the chart does not paint a panel over a 12px bar.
