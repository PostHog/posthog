# Work stream: the "sparklines" that are actually charts

Several surfaces currently render through the shared `Sparkline` wrapper but are not sparklines at all — they have a real axis the user reads, drag-to-select, threshold lines, or an externally-controlled highlighted range.
A sparkline is a glanceable, axis-less spark; the moment a viz grows those features it is a compact **chart** and should migrate to a quill chart component, not to quill `Sparkline`.

This doc splits those surfaces out of the [sparkline work stream](./quill-migration-sparkline.md) and re-targets them.
It **supersedes the "medium" and "heavy" waves** in that doc; the simple wave there (genuine sparklines) is unchanged and stays on quill `Sparkline`.
Part of the broader effort — see [quill-chart-migration.md](./quill-chart-migration.md).

## The test: sparkline or chart?

It's a **chart** (migrate to a quill chart component) if it has any of:

- a visible axis the user reads values off (time axis, categorical/bucket axis) — in the legacy code this shows up as `withXScale` / `withYScale`
- drag-to-select or drag-to-zoom — `onSelectionChange`
- threshold / reference lines — `referenceLines`
- an externally-controlled persistent highlight — `highlightedRange`
- "incomplete/partial" bar striping tied to data recency — `incompleteBars`
- a standalone legend — e.g. the hand-rolled `MetricsChartLegend`

It stays a **sparkline** (quill `Sparkline`, already handled) if it is compact, axis-less, non-interactive, and embedded inline (table cell, stat card, list row).
Small stacked multi-series is still a sparkline when it meets those constraints (e.g. `AppMetricsSparkline`'s success/failure stack) — multi-series alone does not promote it to a chart.

## Reclassification (verified against master, 2026-07-17)

### Stays a sparkline — no change from the sparkline work stream

| Surface | File | Why it's genuinely a sparkline |
| --- | --- | --- |
| App metrics | `frontend/src/lib/components/AppMetrics/AppMetricsSparkline.tsx` | 2-series stacked, `maximumIndicator={false}`, no axes/interactions |
| Hog function estimates | `frontend/src/scenes/hog-functions/metrics/HogFunctionEventEstimates.tsx` | single bar series |
| AI gateway spend | `products/ai_gateway/frontend/gatewayUsage.tsx` | single bar, currency tooltip, `loading` |
| Links clicks | `products/links/frontend/LinkMetricSparkline.tsx` | single series, `maximumIndicator={false}` |
| Logs patterns/services | `products/logs/frontend/components/LogsPatterns/LogsPatterns.tsx`, `LogsServices/LogsServices.tsx` | in-table trend cells |
| Ingestion warnings v1/v2 | `frontend/src/scenes/data-management/ingestion-warnings{,-v2}/…` | flat-array bars |
| Customer analytics | `products/customer_analytics/frontend/components/UsageMetricCard.tsx` | no-axes stat card (consider quill `MetricCard`) |
| Engineering analytics | `products/engineering_analytics/frontend/components/TrendCard.tsx` | sentiment-colored line, no axes |
| HogQLX `<Sparkline>` tag | `frontend/src/queries/nodes/HogQLX/render.tsx` | author-supplied simple props; genuinely a spark element |

### Promote to a chart — moved out of the sparkline waves

| Surface | File | Legacy features present | Target quill component |
| --- | --- | --- | --- |
| Hog function invocations | `frontend/src/scenes/hog-functions/invocations/InvocationsSparkline.tsx` | `withXScale` (time axis), `onSelectionChange` (drag-select), tooltip filters | `TimeSeriesBarChart` + `onDateRangeZoom` |
| Metrics series | `products/metrics/frontend/components/MetricsSeriesChart.tsx` (+ `MetricsViewer.tsx`) | `type="line"`, `withXScale` (time axis), external `MetricsChartLegend` | `TimeSeriesLineChart` with `config.legend` — **delete `MetricsChartLegend.tsx`** |
| Logs sampling preview | `products/logs/frontend/components/LogsSampling/LogsSamplingForm.tsx` | `referenceLines` (rate-limit thresholds), multi-series | `TimeSeriesBarChart` + `ReferenceLine` |
| Logs viewer volume | `products/logs/frontend/components/LogsViewer/LogsViewerSparkline/index.tsx` | `withXScale`, `onSelectionChange`, `highlightedRange`, `incompleteBars` | `TimeSeriesBarChart` (heaviest) |
| Tracing volume/duration | `products/tracing/frontend/TracingSparkline.tsx` | `withXScale`, `onSelectionChange`, `highlightedRange`, dual mode | `TimeSeriesBarChart` (volume) / `BarChart` (duration histogram) |
| Tracing operation histogram | `products/tracing/frontend/OperationHistogram.tsx` | categorical bucket axis (`withCategoryXScale`), `onSelectionChange`, `highlightedRange` | `BarChart` (histogram) |

Type-only importers to repoint when the wrapper's `SparklineTimeSeries`/`SparklineReferenceLine` types move: `logsAlertDetailSceneLogic.ts`, `metricsViewerLogic.tsx`, `MetricsChartLegend.tsx` (the last is deleted outright).

## What this changes vs the sparkline doc

- The sparkline doc's plan tried to keep every consumer on one `Sparkline` prop surface and extend quill `Sparkline` (drag-select, reference lines, time axes) to cover the medium/heavy waves. **Don't.** Those consumers migrate to real chart components with their own idiomatic props instead — no forcing chart features through a sparkline shim.
- The step-1 quill capabilities (`HighlightedRange` overlay, per-bar `hatch`, categorical `onDateRangeZoom`) are still needed — they now land on the **charts** (`TimeSeriesBarChart`/`BarChart`), which is where they belong, rather than on quill `Sparkline`.
- The in-place flag dispatch shipped in step 2 stays as-is for the genuine sparklines. The promoted surfaces don't need the flag — each is a self-contained component swap, verifiable side-by-side, so migrate them directly (short-lived flag only where the interaction risk warrants it, e.g. LogsViewer's drag-select + virtualized-row highlight).

## Suggested PR sequence

Each is an independent, self-contained component swap — no shared flag needed across them.

1. **Metrics series → `TimeSeriesLineChart`** and delete `MetricsChartLegend` (cleanest win: replaces a hand-rolled legend with `config.legend`).
2. **Hog function invocations → `TimeSeriesBarChart`** with `onDateRangeZoom` for the drag-select.
3. **Logs sampling → `TimeSeriesBarChart` + `ReferenceLine`** for the rate-limit thresholds.
4. **Tracing operation histogram → `BarChart`** (categorical buckets, drag-select, highlight).
5. **Tracing volume/duration → `TimeSeriesBarChart`/`BarChart`** (dual mode).
6. **Logs viewer volume → `TimeSeriesBarChart`** — last and heaviest: per-second granularity, drag-select, `highlightedRange` mirroring the virtualized row window, `incompleteBars` via per-bar `hatch`. Behind a short-lived flag with side-by-side verification.

After 1–6, the wrapper's advanced props (`onSelectionChange`, `highlightedRange`, `incompleteBars`, `referenceLines`, `withXScale`/`withYScale`) have no callers left — drop them from `Sparkline.tsx`, collapsing it to the genuine-sparkline surface, and fold the cleanup into the sparkline doc's final step.

## Testing

Use `@posthog/quill-charts/testing` (`getHogChart`, tooltip accessors) per surface: drag-select index reporting, reference-line placement, highlighted-range coverage, histogram bucket rendering.
Invoke `/writing-tests` before authoring; parameterize repeated variations.
The legacy wrapper had only stories and no unit tests, so these are net-new coverage — call that out so they earn their place rather than pinning current behavior.

## Open questions

- **Tracing dual mode**: one component that swaps `TimeSeriesBarChart`↔`BarChart` on `durationMode`, or split into two components? Leaning two — the axes and interactions differ enough that a single prop-forked component stays awkward.
- **LogsViewer `incompleteBars`**: confirm the step-1 per-bar `hatch` gives the right "not-yet-complete" read at per-second granularity, or whether the faded-fill look needs porting (noted as deferred on #70223).
