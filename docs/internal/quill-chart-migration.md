# Quill chart migration — audit and plan

Status of the migration from Chart.js / D3 / bespoke chart code to `@posthog/quill-charts` (`packages/quill/packages/charts`), plus a phased plan for the remaining surfaces.
Audited 2026-07-11.

## Where we are

**Done (unconditional, no flag):**

- Trends: line, bar, area, pie, slope, lifecycle — `products/product_analytics/frontend/insights/trends/`
- Stickiness, retention, funnels (steps bar, horizontal bar, line, histogram) — same tree
- Box plot (`frontend/src/scenes/insights/views/BoxPlot/BoxPlotChart.tsx`), Metric card
- Surveys: multiple-choice and rating bar charts (`frontend/src/scenes/surveys/components/question-visualizations/`)
- Products fully on quill: `mcp_analytics`, `revenue_analytics`, `replay_vision`; `engineering_analytics` partially (MetricTile/StatCard); `metrics` partially (`MetricStatPanel`)

**Rolling out:**

- SQL / DataViz insights behind `PRODUCT_ANALYTICS_QUILL_SQL_CHARTS` — dispatchers in `frontend/src/queries/nodes/DataVisualization/Components/Charts/{LineGraph,PieChart}.tsx` pick `SqlLineGraph` / `SqlBarGraph` / `SqlComboGraph` / `SqlPieGraph` (quill) vs the legacy Chart.js path
- Cosmetic flags on the already-migrated charts: `PRODUCT_ANALYTICS_QUILL_LEGEND`, `QUILL_CHART_STYLE_REFRESH`, `INSIGHT_DRAG_TO_ZOOM`

## What's left (inventory)

### A. Chart.js via the shared `Sparkline` wrapper

`frontend/src/lib/components/Sparkline.tsx` (~520 lines) is the most-reused non-quill primitive.
Quill ships its own `Sparkline`, but nothing in the app imports it yet.
Consumers:

| Surface | File |
| --- | --- |
| Logs viewer volume chart | `products/logs/frontend/components/LogsViewer/LogsViewerSparkline/index.tsx` |
| Tracing volume + duration histogram | `products/tracing/frontend/TracingSparkline.tsx`, `OperationHistogram.tsx` |
| Links click sparkline | `products/links/frontend/LinkMetricSparkline.tsx` |
| Customer analytics usage cards | `products/customer_analytics/frontend/components/UsageMetricCard.tsx` |
| AI gateway spend chart | `products/ai_gateway/frontend/gatewayUsage.tsx` |
| Engineering analytics trend card | `products/engineering_analytics/frontend/components/TrendCard.tsx` |
| Metrics series chart | `products/metrics/frontend/components/MetricsSeriesChart.tsx` |
| Hog functions / CDP | `HogInvocations`, `InvocationsSparkline`, `HogFunctionsList`, `HogFunctionEventEstimates` |
| Ingestion warnings v1/v2, app metrics | `AppMetricsSparkline.tsx` and friends |
| HogQLX `<Sparkline>` render | `frontend/src/queries/nodes/HogQLX/render.tsx` |

Gap: the shared component supports multi-series with breakdowns, custom tick/x-scale formatting, and drag-to-select ranges; quill `Sparkline` is a flat `number[]`.
Logs/tracing drag-select maps to quill's `onDateRangeZoom`; multi-series likely means these migrate to `TimeSeriesBarChart`/`TimeSeriesLineChart` rather than quill `Sparkline`.

### B. Chart.js via the DataViz `LineGraph` (rides the SQL flag)

The `LineGraph` exported from `~/queries/nodes/DataVisualization/Components/Charts/LineGraph.tsx` is itself the flag dispatcher, so **every** importer — not just the SQL editor — switches to quill the moment `PRODUCT_ANALYTICS_QUILL_SQL_CHARTS` is enabled for a user.
`goalLines` are plumbed through the quill adapters (`sqlLineGraphAdapter.ts` → `schemaGoalLinesToConfigs`), but none of these surfaces have been explicitly tested on the quill path yet — verify each before widening the rollout:

- App metrics: `AppMetricSummary.tsx`, `AppMetricsTrends.tsx` (also used by workflows metrics tabs)
- Workflows editor panel metrics: `products/workflows/frontend/Workflows/hogflows/panel/HogFlowEditorPanelMetrics.tsx`
- Error tracking rate limiting: `products/error_tracking/frontend/scenes/ErrorTrackingConfigurationScene/rate_limit/{RateLimitHistoryChart,RateLimitSimulationChart}.tsx` (uses `goalLines`)
- Endpoints usage trends: `products/endpoints/frontend/nodes/EndpointsUsageTrendsNode.tsx`
- Data warehouse editor `OutputPane.tsx`, `DataVisualization.tsx`

### C. Direct Chart.js (`lib/Chart` + `useChart`) — bespoke, highest effort

| Surface | Files | Notes |
| --- | --- | --- |
| Billing | `frontend/src/scenes/billing/BillingLineGraph.tsx` + tooltip + marker positioning (~500 lines) | Straight `TimeSeriesLineChart` fit |
| Experiments timeseries | `frontend/src/scenes/experiments/MetricsView/new/VariantTimeseriesChart.tsx` | Confidence bands map to quill fill-between ribbons |
| Experiments exposures | `frontend/src/scenes/experiments/ExperimentView/Exposures.tsx` (two `useChart` components) | `TimeSeriesLineChart` fit |
| Alerts | `products/alerts/frontend/views/{AlertHistoryChart,SimulationSummary}.tsx` | Uses `chartjs-plugin-annotation`; quill `ReferenceLines` + `AnomalyPointsLayer` cover most of it; dual y-axis supported via `yAxis` array |
| Logs alert simulation | `products/logs/frontend/components/LogsAlerting/LogsAlertSimulation.tsx` | Same pattern as alerts |
| Web analytics live dashboard | `frontend/src/scenes/web-analytics/LiveMetricsDashboard/liveWebAnalyticsMetricsCharts.tsx` + `useLiveChart.tsx` | Imperative per-tick `chart.update('none')`; needs a quill re-render-without-animation story |
| AI observability cluster scatter | `products/ai_observability/frontend/clusters/{ClusterScatterPlot,ClusterDetailScatterPlot}.tsx` | Quill has no scatter chart; needs a new chart type on the `Chart` base primitive |
| Debug CH queries | `frontend/src/lib/components/Shortcuts/utils/DebugCHQueriesImpl.tsx` | Internal tool, do last or leave |

### D. Legacy insight Chart.js remnants (cleanup, mostly deletion)

- `frontend/src/scenes/insights/views/LineGraph/PieChart.tsx` (~300 lines) — last real consumer is the survey single-choice viz (`SingleChoiceQuestionViz.tsx`) plus the flag-gated DataViz fallback
- `frontend/src/scenes/insights/views/LineGraph/LineGraph.tsx` — no JSX consumers left; only exports types/`onChartClick` used by the legacy pie
- `frontend/src/lib/components/AnnotationsOverlay/` — coupled to Chart.js pixel positions; quill charts have their own `AnnotationsLayer`
- `frontend/src/lib/Chart.ts` + `frontend/src/lib/hooks/useChart.ts` + the `chart.js` dependency itself — deletable only at the very end

### E. Custom D3 / SVG that could become quill

- Error tracking `VolumeSparkline` (`products/error_tracking/frontend/components/VolumeSparkline/`, ~540 lines of imperative D3) — drag-select, spike striping, event markers; the biggest bespoke viz in `products/`
- Engineering analytics `FailureSparkline` / `PushHistorySparkline` (raw SVG)
- Experiments new-view violin/delta cells (`MetricsView/new/{ChartCell,ChartGradients,GridLines}.tsx`) — bespoke SVG; could build on quill's `Chart` primitive or stay custom

### F. Out of scope for quill (different visualization kinds)

No quill equivalent exists and these aren't chart-library shaped; leave as-is unless quill grows the component:

- World map / region map (`WorldMap.tsx` static SVG country vectors, `RegionMap.tsx` react-simple-maps) and web analytics `LiveWorldMap`
- Paths v1/v2 (D3 Sankey, vendored `frontend/src/vendor/d3/sankey.ts`)
- Calendar heatmap (custom table), heatmap.js canvas overlays
- Session replay seekbar / user activity / APM waterfall (player-coupled CSS/SVG)
- AI observability `TraceTimeline` (div-based Gantt), funnel flow graph (React Flow), debug signals force graph
- Experiments frozen legacy view (`legacy/metricsView/` — explicitly "do not modify"; delete with legacy experiments)

## Plan

Ordered by leverage per unit of effort; each phase is independently shippable.

Detailed, agent-ready plans exist for three work streams:

- [Sparkline replacement](./quill-migration-sparkline.md) — the shared Chart.js sparkline and its ~18 consumers
- [Billing line graph](./quill-migration-billing.md) — `BillingLineGraph` and the period-marker overlay
- [Experiments charts](./quill-migration-experiments.md) — exposures charts and the variant timeseries with CI bands

### Phase 1 — finish the SQL rollout and delete the legacy insight path

1. Complete the `PRODUCT_ANALYTICS_QUILL_SQL_CHARTS` rollout, first testing the group-B consumers (app metrics stacked bars, `goalLines` in the error tracking rate-limit charts, workflows panel metrics, endpoints usage trends) on the quill path — they flip with the flag but haven't been individually verified.
2. Migrate the survey single-choice pie to quill `PieChart` (pattern already exists in `TrendsPieChart` and the sibling survey bar charts).
3. Delete `LegacyLineGraph` / `LegacyPieChart` from DataViz, then `scenes/insights/views/LineGraph/{LineGraph,PieChart}.tsx` and `AnnotationsOverlay/`.
4. Retire `PRODUCT_ANALYTICS_QUILL_LEGEND` and `QUILL_CHART_STYLE_REFRESH` once fully rolled out.

### Phase 2 — the shared Sparkline (one migration, ~10 surfaces)

1. Gap analysis: quill `Sparkline` vs `lib/components/Sparkline` (multi-series/stacked breakdowns, custom tick labels, drag-to-select, hover tooltips).
2. Extend quill (or route multi-series cases to `TimeSeriesBarChart`) and build a drop-in `Sparkline` replacement in `lib/components/`, keeping the existing prop surface so consumers don't all change at once.
3. Migrate simple consumers first (links, ai_gateway, customer_analytics, engineering_analytics `TrendCard`, hog functions, ingestion warnings), then the complex ones (logs and tracing need drag-select via `onDateRangeZoom`; tracing's histogram mode; metrics `MetricsSeriesChart`).
4. Update the HogQLX `<Sparkline>` renderer last (user-visible in query outputs — screenshot-test it).

### Phase 3 — straightforward bespoke Chart.js charts

In rough order: billing `BillingLineGraph`, experiments `VariantTimeseriesChart` (fill-between ribbons for confidence bands) and `Exposures`, alerts `AlertHistoryChart` / `SimulationSummary` (ReferenceLines + AnomalyPointsLayer), logs `LogsAlertSimulation`.
Each is a self-contained PR behind a short-lived flag if risk warrants.

### Phase 4 — quill component gaps

1. **Scatter chart**: build on the `Chart`/`RadialChart`-style base primitive; unlocks the AI observability cluster plots (which also need `chartjs-plugin-zoom`-equivalent pan/zoom).
2. **Live/streaming updates**: a no-animation incremental update path; unlocks the web analytics live dashboard.
3. Optionally: richer sparkline annotations (spike striping, event markers) to absorb error tracking's `VolumeSparkline`.

### Phase 5 — endgame

1. Migrate or consciously keep the remaining custom SVG (engineering analytics sparklines, experiments violin cells).
2. Remove `frontend/src/lib/Chart.ts`, `useChart.ts`, `chartjs-plugin-*`, and the `chart.js` dependency once `git grep "lib/Chart"` is clean.

## Suggested first PRs

1. Survey single-choice pie → quill (small, unblocks deleting the legacy insight `PieChart`).
2. Sparkline gap analysis + quill extension proposal (design doc or spike PR in `packages/quill/packages/charts`).
3. Billing `BillingLineGraph` → `TimeSeriesLineChart` (self-contained, high visibility).
