# Work stream: replace the shared Chart.js Sparkline with quill

Goal: delete `frontend/src/lib/components/Sparkline.tsx` (Chart.js + `chartjs-plugin-annotation`, ~520 lines) and move all ~18 consumers to `@posthog/quill-charts`.
Part of the chart.js removal effort — see [quill-chart-migration.md](./quill-chart-migration.md).

## Key insight

Quill's `Sparkline` component is NOT the target for most consumers.
It is single-series, line-only, `number[]` data, no tooltip (hardcoded `tooltip: { enabled: false }`), no bars, no drag-select.
Most consumers need compact-configured `BarChart` / `TimeSeriesBarChart` / `TimeSeriesLineChart` (hidden axes, no legend, tight margins) instead.

## Legacy feature surface that must be preserved

From `frontend/src/lib/components/Sparkline.tsx`:

- `data: number[] | SparklineTimeSeries[]` — multi-series, always **stacked** when multiple
- `type: 'bar' | 'line'` (default bar — most consumers use bars)
- `onSelectionChange({startIndex, endIndex})` — drag-to-select with in-progress overlay + Escape cancel
- `highlightedRange` — persistent translucent box mirroring an external range (annotation plugin)
- `incompleteBars` — diagonal-hatch pattern on given bar indices + warning row in tooltip
- `referenceLines` — dashed horizontal threshold lines with labels; y-axis auto-expands with headroom
- `withXScale` / `withYScale` — raw Chart.js scale escape hatches (time axes, category axes, hiding axes)
- Tooltip options: `renderLabel`, `renderTooltipValue`, `tooltipRowCutoff`, `hideZerosInTooltip`, `sortTooltipByCount` (rendered via `InsightTooltip`)
- `maximumIndicator` — y-axis showing only the max tick
- Semantic color names (`'success'`, `'danger'`, `'muted'`) resolved via `getColorVar`
- `loading` → `LemonSkeleton`

## Consumer inventory (what each actually uses)

Simple (single/simple series, no axes, no interactions):

- `frontend/src/scenes/data-management/ingestion-warnings-v2/IngestionWarningsV2View.tsx` and v1 — flat array bars
- `frontend/src/scenes/hog-functions/metrics/HogFunctionEventEstimates.tsx` — single bar series
- `products/ai_gateway/frontend/gatewayUsage.tsx` — single bar series, currency `renderTooltipValue`, `loading`
- `products/links/frontend/LinkMetricSparkline.tsx` — single series bars, `loading`
- `products/logs/frontend/components/LogsPatterns/LogsPatterns.tsx`, `LogsServices.tsx` — in-table trend cells
- `frontend/src/lib/components/AppMetrics/AppMetricsSparkline.tsx` — two-series stacked bars (success/failure)
- `products/customer_analytics/frontend/components/UsageMetricCard.tsx` — no-axes sparkline in a stat card; **consider adopting quill `MetricCard` wholesale**
- `products/engineering_analytics/frontend/components/TrendCard.tsx` — sentiment-colored line; quill `Sparkline` or `MetricCard` fits 1:1

Medium (time axis, tooltip filters, reference lines, drag-select):

- `frontend/src/scenes/hog-functions/invocations/InvocationsSparkline.tsx` — multi-series bars, timeseries x-axis, drag-select, `hideZerosInTooltip`/`sortTooltipByCount`
- `products/logs/frontend/components/LogsSampling/LogsSamplingForm.tsx` — stacked multi-series + rate-limit `referenceLines`
- `products/metrics/frontend/components/MetricsSeriesChart.tsx` + `MetricsViewer.tsx` — multi-series lines, timeseries x-axis; target `TimeSeriesLineChart` with `config.legend` and **delete `MetricsChartLegend.tsx`** (quill legend replaces it)

Heavy (nearly every advanced feature):

- `products/logs/frontend/components/LogsViewer/LogsViewerSparkline/index.tsx` — multi-series stacked bars, per-second time granularity, drag-select, `highlightedRange` (mirrors virtualized row window), `incompleteBars`, tooltip cutoff 100
- `products/tracing/frontend/TracingSparkline.tsx` — dual mode (timeseries volume vs categorical duration histogram), drag-select, `highlightedRange`; external `SparklineCompareOverlay` is independent and unaffected
- `products/tracing/frontend/OperationHistogram.tsx` — categorical (log-spaced duration buckets) x-axis, drag-select, persistent highlight

Special:

- `frontend/src/queries/nodes/HogQLX/render.tsx` — the HogQLX `<Sparkline>` tag passes through arbitrary author-supplied props; needs the richest wrapper and screenshot tests; migrate **last**
- Type-only importers (`SparklineTimeSeries`): `logsAlertDetailSceneLogic.ts`, `metricsViewerLogic.tsx`, `MetricsChartLegend.tsx` — update the type import path

Not consumers (do not touch): `engineering_analytics` `FailureSparkline`/`PushHistorySparkline` (raw SVG) and `error_tracking` `VolumeSparkline` (D3) are independent implementations.

## Quill gaps to close first (in `packages/quill/packages/charts`)

1. **Highlighted-range overlay** — a reusable overlay child (translucent box from an index/label range, via `useChartLayout()` scales). Needed by LogsViewerSparkline, TracingSparkline, OperationHistogram.
2. **Per-bar hatch/pattern fill** in `BarsConfig` for the `incompleteBars` equivalent (LogsViewerSparkline). Alternative: custom overlay drawing pass.
3. **Verify `onDateRangeZoom` works with non-date categorical labels** (duration buckets). Its `{startIndex, endIndex}` shape looks label-generic already — confirm and document.
4. **Semantic-color helper** — map PostHog color names to quill's `color` prop (thin app-side shim using the existing `getColorVar`).
5. Nice-to-have: a "max tick only" y-axis mode for `maximumIndicator` parity (or accept dropping it — most consumers set it `false` anyway).

Per quill's `AGENTS.md`, update that guide in the same PR as any quill API change.

## Recommended approach

Refactor `lib/components/Sparkline.tsx` **in place**: keep the existing prop surface, render quill internally, gate legacy vs quill with a short-lived feature flag (like `PRODUCT_ANALYTICS_QUILL_SQL_CHARTS`).
This gives one dispatch point, zero consumer churn during rollout, and per-consumer simplification can follow later.
Internal dispatch: `type==='line' && single series && no extras` → quill `Sparkline`; bars → compact `BarChart`/`TimeSeriesBarChart` (stacked); time axes via `config.xAxis` instead of `withXScale`.
`withXScale`/`withYScale` are Chart.js-specific escape hatches — audit each call site and translate to structured quill config; do not try to support them generically.

## Suggested PR sequence

1. Quill capability PR(s): highlighted-range overlay, hatch pattern, categorical `onDateRangeZoom` verification + tests/stories.
2. In-place quill rendering path in `Sparkline.tsx` behind a flag, covering the simple-consumer feature set; migrate + verify the simple wave.
3. Medium wave: time axes, reference lines, drag-select (InvocationsSparkline, LogsSamplingForm, metrics product; delete `MetricsChartLegend`).
4. Heavy wave: LogsViewerSparkline, TracingSparkline, OperationHistogram — one PR each, with side-by-side manual verification.
5. HogQLX tag + screenshot/story coverage.
6. Cleanup: remove the Chart.js path and the flag, update `Sparkline.stories.tsx`, drop `chartjs-plugin-annotation` registration (note: `products/alerts` also registers it — coordinate with the alerts work stream).

## Testing

The legacy component has stories only (`Sparkline.stories.tsx`, 2 stories) and no unit tests — behavior like drag-select math and tooltip filtering is currently unverified.
Add tests with `@posthog/quill-charts/testing` (`getHogChart`, tooltip accessors) for: stacked multi-series rendering, drag-select index reporting, reference line placement, highlighted range, and tooltip filter options.
Invoke `/writing-tests` before authoring; parameterize where variations repeat.
