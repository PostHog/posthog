# Metrics dashboard panels: design

Status: draft for review by the metrics team.
Scope: the `products/metrics` product and the dashboard surfaces that render a `MetricsQuery` tile.

## 1. Problem

People who move from Grafana expect a metrics dashboard to have stat, gauge, bar gauge, table, and heatmap panels, unit formatting, threshold colors, template variables, and a fast refresh.
Our metrics tiles render a line, area, or bar chart only.
The `stat` display type is in the schema but has no renderer and falls back to a line chart.
The OTel `unit` is stored and returned by the catalog but no chart reads it.

Adoption shows the effect.
In project 2 there are 38 saved metrics insights.
None set `display`, none use a formula, one uses `groupBy`.
The query engine supports all of these, but a dashboard built from them does not look like a metrics dashboard yet.

## 2. Goals and non-goals

Goals:

- Add stat, gauge, bar gauge, table, and heatmap panels for a `MetricsQuery` tile.
- Format values with the OTel unit on every panel, axis, tooltip, and legend.
- Color a value by a threshold list.
- Show legend calculations (min, max, mean, last) on time-series panels.
- Render a null bucket as a gap, not as zero.
- Make each panel a pure consumer of the existing query response, so one ClickHouse query feeds every panel type.
- Do not change how any non-metrics insight renders, caches, alerts, or exports.

Non-goals for this design:

- Dashboard template variables that filter every metrics tile (`$service`). This needs a schema change to `MetricsQueryFilter` and a runner change. It is a separate design, listed in section 11.
- Refresh intervals faster than 30 minutes. This is a dashboard-wide cost question, also in section 11.
- Geomap, node graph, and canvas panels. We do not ingest the data they need.
- A Grafana JSON importer. It becomes useful only after the panels exist.

## 3. What exists today

| Piece | Location | Note |
| --- | --- | --- |
| Query node | `frontend/src/queries/schema/schema-general.ts` (`MetricsQuery`, `MetricsDisplaySettings`) | Clauses, aggregations, filters, `groupBy`, formula, interval. `display` is presentation only. |
| Runner | `products/metrics/backend/hogql_queries/metrics_query_runner.py` | `get_cache_payload` drops `display` so a chart change does not re-run ClickHouse. `apply_dashboard_filters` applies the dashboard date range only. |
| Facade | `products/metrics/backend/facade/api.py` | `run_metric_query` returns `list[MetricSeries]`. `value` on a point is `float | None`. |
| Tile renderer | `products/metrics/frontend/nodes/MetricsQueryNode.tsx` | Strips `display` before it builds `dataNodeLogic`, for the same cache reason. |
| Chart | `products/metrics/frontend/components/MetricsSeriesChart.tsx` | `isBar ? TimeSeriesBarChart : TimeSeriesLineChart`. Charts `null` as `0`. Hides the legend for one series. |
| Chart config | `products/metrics/frontend/components/metricsChartConfig.ts` | Axis scale, bounds, goal lines, tooltip. No unit. |
| Settings UI | `products/metrics/frontend/components/MetricsChartSettings.tsx` | Display type, scale, bounds, goal lines. |
| Catalog | `products/metrics/backend/metric_names_query_runner.py` | Returns `unit` per metric name. The frontend does not pass it to the chart. |
| Histogram storage | `posthog/clickhouse/metrics/metric_events.py` | `histogram_bounds Array(Float64)`, `histogram_counts Array(UInt64)` on each sample row. |
| Alerts | `posthog/tasks/alerts/metrics_investigation.py` | Selects by `alertable_query_kind == NodeKind.METRICS_QUERY`. Reads the response, not `display`. |
| Export | `frontend/src/exporter/ExportedInsight/ExportedInsight.tsx` | `isMetricInsightQuery` already special-cases a metrics insight and renders it through the generic `Query` component. |
| Chart library | `packages/quill/packages/charts` (`@posthog/quill-charts` 0.3.0-beta.16) | Exports `MetricCard`, `Sparkline`, `BarChart`, `Heatmap`, `PieChart` on a `RadialChart` core. `Series.data` is `number[]`, so it cannot draw a gap. |
| Isolation | `tach.toml` | `products.metrics` depends on `posthog`, `products.access_control`, `products.error_tracking`. It is sealed: `backend:contract-check` exists. |

## 4. Design

### 4.1 One pipeline for every panel

Every Grafana panel is the same five steps: query, series, reduce, format, render.
We have query, series, and render.
This design adds reduce and format as pure modules, and turns render into a registry.

```text
MetricsQuery ──runner──▶ MetricsQuerySeries[] ──reduce──▶ number per series ──format──▶ string + color ──▶ panel
                                    │
                                    └──────────────────────────────────────────────────────────────────▶ time-series panel
```

The response shape does not change for any panel except the heatmap.
`display` stays out of the cache key, so switching a tile from line to stat to table costs no ClickHouse query.

### 4.2 Schema additions

All additions are optional fields on `MetricsDisplaySettings`.
An existing insight with no `display`, or with today's `display`, renders exactly as it does now.

```ts
export type MetricsDisplayType = 'line' | 'area' | 'bar' | 'stat' | 'gauge' | 'bargauge' | 'table' | 'heatmap'

/** How a series collapses to one number. */
export type MetricsReducer = 'last' | 'mean' | 'min' | 'max' | 'sum' | 'delta'

export interface MetricsThreshold {
    /** Applies from this value up to the next threshold. The first step should use -Infinity or be omitted for a base color. */
    value: number
    /** A named color token, never a raw hex, so light and dark themes both work. */
    color: string
}

export type MetricsNullMode = 'gap' | 'zero' | 'connect'

export interface MetricsDisplaySettings {
    type?: MetricsDisplayType
    goalLines?: GoalLine[]
    yAxis?: MetricsYAxisSettings
    /** @deprecated Use `reduce`. Kept so saved insights keep working; read as `last`, `mean`, `sum`. */
    statSummary?: MetricsStatSummary
    reduce?: MetricsReducer
    /** UCUM unit string as OTel writes it, e.g. "By", "ms", "1", "%", "{req}/s". Defaults from the response unit. */
    unit?: string
    thresholds?: MetricsThreshold[]
    /** @default gap */
    nullMode?: MetricsNullMode
    /** Time-series panels only: which reducers the legend table shows. */
    legendCalcs?: MetricsReducer[]
}
```

`MetricsQuerySeries` gets one optional field:

```ts
export interface MetricsQuerySeries {
    ...
    /** UCUM unit of the metric as ingested. Empty when the SDK did not set one. */
    unit?: string
}
```

The `statSummary` to `reduce` mapping is `latest → last`, `average → mean`, `total → sum`.
We keep `statSummary` in the schema because `schema.json` and `posthog/schema.py` are generated and a saved insight can hold it.
A one-line read-side fallback is cheaper and safer than a data migration.

### 4.3 Shared modules

All three live in `products/metrics/frontend/panels/` and have no React and no kea in them.

`metricsReduce.ts`

```ts
export function reduceSeries(points: MetricsQueryPoint[], reducer: MetricsReducer): number | null
export function flattenSeriesRows(series: MetricsQuerySeries[], reducers: MetricsReducer[]): MetricsSeriesRow[]
```

`reduceSeries` skips `null` points.
It returns `null` when no point has a value, so a panel can show "No data" instead of `0`.
`delta` is last minus first non-null value.
`flattenSeriesRows` turns label sets into columns and adds one column per reducer.
The table panel, the bar gauge, and the legend table all use it.

`metricsUnits.ts`

```ts
export function formatMetricValue(value: number, unit: string | undefined): string
export function unitAxisFormatter(unit: string | undefined): (value: number) => string
```

The UCUM table covers the units OTel semantic conventions emit: `By`, `KiBy`, `MiBy`, `s`, `ms`, `us`, `ns`, `1` (a ratio, shown as a percent when the values are in 0 to 1), `%`, `{request}/s` and other `{x}/s` counts, and `1/s`.
An unknown unit falls back to a compact number with the unit string appended.
The mapping is a plain object, so adding a unit is one line and one test row.

`metricsThresholds.ts`

```ts
export function thresholdColor(value: number | null, thresholds: MetricsThreshold[] | undefined, fallback: string): string
```

Thresholds are sorted by `value` before lookup, so the order a user enters them does not matter.

### 4.4 Panel registry

```ts
// products/metrics/frontend/panels/registry.ts
export interface MetricsPanelProps {
    series: MetricsChartSeries[]
    display: MetricsDisplaySettings
    unit: string | undefined
    fallbackName: string
    exemplars?: MetricsExemplar[]
}

export interface MetricsPanelDefinition {
    Component: (props: MetricsPanelProps) => JSX.Element
    label: string
    /** Hidden in the picker unless the query has a groupBy. */
    needsGroupBy?: boolean
    /** Hidden in the picker unless every clause is a histogram metric. */
    needsHistogram?: boolean
}

export const METRICS_PANELS: Record<MetricsDisplayType, MetricsPanelDefinition>
```

`MetricsSeriesChart` becomes a thin dispatcher: look up `display.type ?? 'line'`, fall back to `line` for an unknown type, render.
`MetricsChartSettings` reads the registry to build the picker and disables an entry whose `needsGroupBy` or `needsHistogram` the query does not satisfy, with a `disabledReason`.

The registry is the only place that knows the list of panels.
Adding a panel is one component file, one test file, one story, and one registry line.

### 4.5 The panels

| Panel | Query shape | Reduce | Renders with | New chart code |
| --- | --- | --- | --- | --- |
| Stat | one clause; one card per series when grouped | `reduce` (default `last`) | quill `MetricCard` with `Sparkline` | none |
| Gauge | one clause | `reduce` | new quill `GaugeChart` on the `RadialChart` core | yes, in quill |
| Bar gauge | one clause with `groupBy` | `reduce` per series, sorted | quill `BarChart` (categorical) | none |
| Table | any, best with `groupBy` | `flattenSeriesRows` | `LemonTable` | none |
| Heatmap | histogram metric | none; the runner returns a grid | quill `Heatmap` | none in quill; a new runner |
| Line, area, bar | as today | legend calcs via `reduceSeries` | as today | gap rendering in quill |

Details that need a decision are in section 7.

### 4.6 Heatmap query

A heatmap needs the histogram bucket counts per time bucket, not one number.
This is a new node, not a new field on `MetricsQuery`, because the response shape is different and the cache key must include everything the runner reads.

```ts
export interface MetricsHistogramQuery extends DataNode<MetricsHistogramQueryResponse> {
    kind: NodeKind.MetricsHistogramQuery
    metricName: string
    filters?: MetricsQueryFilter[]
    dateRange?: DateRange
    interval?: string
    display?: MetricsDisplaySettings
}

export interface MetricsHistogramQueryResponse extends AnalyticsQueryResponseBase {
    /** Bucket start per column. */
    times: string[]
    /** Upper bound per row, ascending. */
    bounds: number[]
    /** counts[row][column] */
    counts: number[][]
}
```

The runner sums `histogram_counts` per `(time bucket, bound)` after it aligns bounds.
Explicit-bound histograms share one bound list per series and align directly.
Exponential histograms rescale between emissions, so the runner has to pick a target bound list and rebin.
`products/tracing/backend/latency_heatmap_query_runner.py` already does this for spans and is the model to follow.

A new `NodeKind` touches `Query.tsx`, `dataNodeLogic.ts` response unions, `posthog/schema.py`, `schema.json`, the alertable query kinds, and the MCP query tool list.
Section 6 covers each.

### 4.7 Where the unit comes from

The runner reads `any(unit)` per series from `metric_series` in the same query it already runs, and puts it on `MetricsQuerySeries.unit`.
The chart uses `display.unit ?? series[0].unit`.
A tile then needs no second request to the catalog.
`display.unit` stays as a user override for a metric the SDK did not label.

## 5. How we choose

These are the choices the design makes and the reason for each.
Section 7 lists the choices still open.

| Choice | Chosen | Rejected | Why |
| --- | --- | --- | --- |
| Where the panels live | `products/metrics/frontend/panels/` | `frontend/src/scenes/insights/views/` | Only metrics uses them. `product:lint` only checks `products/`. `/placing-product-frontend-code` says product UI belongs in the product tree. |
| Where the gauge lives | `packages/quill/packages/charts` | inside metrics | It is a generic chart. Error tracking and web analytics have the same need. The `RadialChart` core already exists and `PieChart` proves the pattern. Product code must not fork a chart. |
| Reduce and format modules | pure TypeScript, no kea | kea selectors | They are used inside a chart render, in a legend, in the table, and in tests. A pure function is the smallest unit and is easy to test first. |
| Reducer field name | `reduce`, deprecate `statSummary` | extend `statSummary` | `statSummary` is stat-only by name. The legend, table, and bar gauge need the same vocabulary. |
| Threshold colors | named tokens | hex | `getColorVar` and the chart theme handle light and dark. A hex breaks dark mode. |
| Heatmap query | new `MetricsHistogramQuery` node | a `heatmap` display type on `MetricsQuery` | The response shape is a grid, not series. A display type must not change what the runner reads, or the cache key trick in `get_cache_payload` breaks. |
| Null rendering | default `gap` | keep `zero` | Zero is a lie on a gauge or a rate chart. `gap` matches Grafana and Prometheus. Existing insights get the new default. Section 7 asks whether that needs a change notice. |
| Unit source | runner returns it on the series | frontend joins the catalog | One request per tile instead of two. Dashboards with many tiles would otherwise fan out catalog calls. |
| Rollout gate | the existing `metrics` flag plus a new `metrics-dashboard-panels` flag | the `metrics` flag alone | The product is alpha and already gated. A second flag lets us turn off the new picker without turning off metrics for a team. |

## 6. Not breaking anything else

Each row is a place that reads `MetricsQuery` or the display settings today, what changes, and how we prove it still works.

| Surface | What reads it | Change | Proof |
| --- | --- | --- | --- |
| Insight cache | `MetricsQueryRunner.get_cache_payload` drops `display` | none; new fields are all under `display` | `test_metrics_query_runner.py` has a cache-key test. Add a case that sets every new field and asserts the same key. |
| Tile refetch | `MetricsQueryNode` strips `display` before `dataNodeLogic` | none | `MetricsViewer.test.tsx` covers the strip. Add a case for `thresholds` and `unit`. |
| Dashboard date filter | `apply_dashboard_filters` sets `dateRange` only | none | existing test. |
| Alerts | `metrics_investigation.py` reads response values | none. `reduce` is a display concern. An alert on a stat panel still evaluates the series. | `test_metrics_alerts.py` unchanged. A new test asserts an insight with `display.type = 'stat'` still creates an alert. |
| Export and subscriptions | `ExportedInsight.tsx` renders the generic `Query` | the registry runs inside `MetricsSeriesChart`, so export gets the new panel for free | Render an exported stat tile in Storybook and in `hogli start` through the export URL. |
| Notebooks | the generic `Query` component | same | manual check in a notebook. |
| Saved insights with `statSummary` | schema | read-side map to `reduce` | a unit test for each of the three values. |
| Saved insights with unknown `display.type` (older or newer client) | registry lookup | fall back to `line` | a unit test. |
| Generated Python schema | `posthog/schema.py`, `schema.json` | regenerate with `pnpm schema:build` and `bin/build-schema-python.sh` | CI fails if either is stale. |
| Generated API types | none; no serializer changes for panels | none | `hogli build:openapi` only if the heatmap runner adds an endpoint. It should not; it goes through `/query`. |
| MCP `query-metrics` tool | reads the `MetricsQuery` schema | new optional fields appear in the tool schema automatically | run `info query-metrics` on a dev MCP and check the fields describe themselves. |
| Product isolation | `tach.toml`, `backend:contract-check` | no new backend dependency for panels. The heatmap runner imports `posthog.hogql_queries` only, which is allowed. | `hogli product:lint --all` passes. Do not add a line to `isolation_baseline.txt`. |
| Quill charts consumers | ten products import `@posthog/quill-charts` | additive: new `GaugeChart` export, an optional `null` in `Series.data` | quill's own test suite and stories. Section 7 decides whether `Series.data` becomes `(number | null)[]` or a parallel `gaps` field, because the former touches every chart in the library. |
| Dashboard grid | react-grid-layout sizes | a stat panel is small; set `minW`/`minH` per panel in the registry | render at the smallest tile size in a story. |
| Narrow scenes | 520 px scene width with a side panel | every panel wraps and truncates, per `frontend/src/AGENTS.md` rule 6 | stories at 320 px, 520 px, and 1024 px container widths. |
| Translation extensions | bare text nodes with siblings | the stat headline is a sole child of its element, `translate="no"` on the value | code review; `MetricCard` already wraps the value. |

The change that reaches beyond the metrics product is the gap rendering in quill.
Everything else is inside `products/metrics/` or additive to the generated schema.

## 7. Questions to answer before we write code

Each question has an owner suggestion and a default.
If nobody objects, the default stands.

1. **Null gaps in quill.** `Series.data` is `number[]` across every chart. Options: (a) widen to `(number | null)[]` and teach the draw loop to break the path; (b) add an optional `gaps: boolean[]` beside `data`. (a) is cleaner and matches Chart.js and ECharts. (b) is additive and cannot break another product. Default: (b) for the first release, then (a) as a quill-only follow-up. Owner: quill charts maintainers.
2. **Do existing insights change appearance?** Switching the default `nullMode` from zero to gap changes what a saved line chart shows where data is missing. Options: default `gap` for all, or default `zero` for an insight saved before the release and `gap` for new ones. Default: `gap` for all, with a change notice per `/announcing-behavior-changes`. The old rendering was marked "for now" in the code. Owner: metrics product owner.
3. **Gauge min and max.** Grafana requires them. Options: from `yAxis.min`/`yAxis.max`; from the first and last threshold; auto from the series range. Default: `yAxis` first, thresholds second, series range last, and show the chosen bounds in the settings panel so the user sees them. Owner: design.
4. **Stat per series when grouped.** A `groupBy` query can return dozens of series. Options: a card grid capped at N with "and 12 more"; or refuse stat for grouped queries. Default: a card grid capped at 12, sorted by the reduced value, with a tooltip on the cap. Owner: design.
5. **Threshold color vocabulary.** Options: the six `getColorVar` data colors; a fixed `ok / warn / critical` triple; free named tokens. Default: a fixed set of eight named tokens that map to theme variables, documented in the settings panel. Owner: design.
6. **UCUM coverage.** Which units ship in the first table? Default: bytes and binary bytes, seconds down to nanoseconds, ratio and percent, `{x}/s` rates, `1/s`. Everything else falls back to the unit string. Owner: metrics team. Evidence to gather: `SELECT unit, count() FROM metric_series GROUP BY unit` on a dogfood team.
7. **Where the unit is read.** Default is the runner. The alternative is `metric_names_query_runner` on the frontend. Confirm the join cost: `metric_series` is already joined for labels, so `any(unit)` should be free. Owner: whoever writes the runner change. Evidence: `EXPLAIN` before and after on a dogfood team.
8. **Heatmap bound alignment for exponential histograms.** Pick the scale of the most recent sample, or the coarsest scale in the range? Default: the coarsest, so no bucket needs to be split. Owner: backend. Evidence: read how `latency_heatmap_query_runner.py` bins spans, and check whether any dogfood service emits exponential histograms.
9. **Does the heatmap need a new `NodeKind`?** Default: yes, for the cache-key reason in 4.6. Alternative: return the grid inside `MetricsQueryResponse` under a new field when a `heatmap` display is set, and add the display type to the cache key only in that case. The alternative avoids touching `Query.tsx` and the response unions but makes `display` half-presentation. Owner: metrics team.
10. **Legend table density.** Grafana shows the legend as a table under the chart. On a small dashboard tile this eats the chart. Default: legend calcs are off by default, and on only when `legendCalcs` is set. Owner: design.
11. **Is `bargauge` a separate type or a `bar` option?** Default: a separate type, because it is categorical, not time-series, and the picker rule (`needsGroupBy`) differs. Owner: metrics team.
12. **Feature flag shape.** One new flag `metrics-dashboard-panels` that gates the picker entries. Existing `line`, `area`, `bar` stay ungated. Confirm with the flag owner in `#team-apm`. Owner: metrics team.
13. **Storybook coverage for a product under `products/`.** There are no stories in `products/metrics/frontend` today. `products/logs` has them. Confirm the Storybook config picks up `products/*/frontend/**/*.stories.tsx` and that visual review runs on them. Owner: whoever writes the first panel.
14. **Does the export renderer size a stat tile?** `ExportedInsight` fixes a height for charts. A stat card at that height looks wrong. Default: the registry carries an `exportHeight` per panel and `ExportedInsight` reads it only for a metrics insight. Owner: frontend. Evidence: render one exported stat through the export URL.
15. **Do we need a data migration at all?** Default: no. `statSummary` is read-side mapped. No existing insight sets `display.type` to a removed value. Confirm with `SELECT count() FROM system.insights WHERE toString(query) LIKE '%statSummary%'` on US and EU before we deprecate the field.

## 8. Test plan

Test-driven for every module.
Write the test, run it and watch it fail, then write the code.

Unit, pure TypeScript (`hogli test products/metrics/frontend/panels`):

- `metricsReduce.test.ts`: every reducer on an empty, one-point, all-null, and mixed-null series. `flattenSeriesRows` with zero, one, and two label keys.
- `metricsUnits.test.ts`: `test.each` over the UCUM table with the boundary values 0, 999, 1000, 1023, 1024, 1e9, negative, and an unknown unit.
- `metricsThresholds.test.ts`: unsorted input, a value below the first step, equal to a step, above the last step, `null`.
- `registry.test.ts`: unknown type falls back to line; `needsGroupBy` and `needsHistogram` gating.

Component, Jest and Testing Library:

- One test file per panel. It asserts the visible text the user reads (the formatted value, the "No data" state, the cap message), not canvas pixels.
- `MetricsSeriesChart.test.tsx`: `statSummary` maps to `reduce`; an old insight with no `display` still renders a line chart.

Backend, pytest (`hogli test products/metrics/backend/tests`):

- `test_metrics_query_runner.py`: `unit` appears on every series; the cache key ignores every new display field.
- `test_metrics_histogram_query_runner.py`: explicit bounds sum per bucket; exponential bounds rebin to the coarsest scale; an empty range returns empty arrays, not an error.
- `test_metrics_alerts.py`: an insight with `display.type = 'stat'` still creates and evaluates an alert.

Visual, Storybook:

- One story per panel at three container widths, in light and dark.
- One story for the exported stat tile.

End to end, `hogli start`:

- Build a dashboard with the starter modal on a dogfood team.
- Switch one tile to each panel type and confirm no network request fires in the browser devtools when only `display` changes.
- Export the dashboard as an image and check the stat tile.
- Create an alert on the stat tile and simulate it.

## 9. Rollout

1. Ship the foundation behind `metrics-dashboard-panels` set to no one. Nothing visible changes.
2. Turn it on for the PostHog dogfood team. Convert the `[APM: Distributed Tracing] Official` and `[APM: Logs] Official V2` dashboards to use stat and table panels where a headline number is the point. Live with them for a week.
3. Turn it on for the teams in the metrics alpha.
4. Remove the flag once the picker has been stable for two weeks and the change notice for gaps has been shown.

Metrics to watch, all from the existing `metricsUsageTrackingLogic` events plus `system.insights`:

- Saved metrics insights by `display.type`.
- Dashboards with three or more metrics tiles.
- Weekly viewers of those dashboards.
- Frontend exceptions in `products/metrics/frontend/panels/` in error tracking.
- p95 of `/query` for `MetricsQuery` before and after the `unit` join, on the LOGS cluster.

## 10. Order of work

Each item is one PR, gated, and independently reviewable.

1. Foundation: schema fields, `reduce`, `units`, `thresholds`, registry, `unit` on the response, `statSummary` mapping. Tests first. No picker entries yet.
2. Stat, bar gauge, table. Three panels that are pure consumers of the foundation.
3. Gauge: `GaugeChart` in quill, then the metrics panel.
4. Gaps: quill change for null data, then `nullMode` in metrics, then the change notice.
5. Legend calcs on the time-series panel.
6. Heatmap: `MetricsHistogramQuery` runner and panel.
7. Docs update under `docs/` in the same PR as each user-facing change.

## 11. Follow-up designs

These are out of scope here but are the next things a Grafana user asks for.

- **Dashboard variables for metric labels.** `MetricsQueryFilter.value` accepts `{variables.service}`. A new `InsightVariableType` sourced from `list_metric_attribute_values`. `apply_variable_overrides` in `query_runner.py` today returns early unless the kind is `HogQLQuery`, so `MetricsQueryRunner` needs its own override. This crosses `products.product_analytics` (the variable model) and `products.metrics`, so it needs a tach decision.
- **Fast refresh for metrics-only dashboards.** `REFRESH_INTERVAL_SECONDS` is `[1800, 3600]`. A metrics dashboard wants 10 s to 5 min. This multiplies LOGS-cluster queries per tile and needs a per-team floor and a cost dashboard before it ships.
- **Shared crosshair across tiles.** Hover time synced through `dashboardLogic`. Quill would need a controlled hover index on `TimeSeriesLineChart`.
- **Grafana JSON import.** A PromQL subset to `MetricsQuery` translator and a panel-type map. Valuable only once the panels above exist.
