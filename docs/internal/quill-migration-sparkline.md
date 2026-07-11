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

## Handover — status after step 1 (2026-07-11)

### Done

Step 1 of the PR sequence (quill capability PR) is up as [#70223](https://github.com/PostHog/posthog/pull/70223), reviewed and awaiting merge:

- **`HighlightedRange` overlay** (`packages/quill/packages/charts/src/overlays/HighlightedRange.tsx`, exported from the package index). `start`/`end` accept data indices or labels, so it can be fed directly from `onDateRangeZoom` output or from label-based external state. Band-aware via `scales.extent` (covers whole bars on bar charts, point-to-point on line charts), clamps to the plot area, renders null on unresolvable endpoints. Testing hook: `data-attr="hog-chart-highlighted-range"`.
- **Per-bar hatch**: `Series.bars[i].hatch` hatches individual bars at arbitrary (non-contiguous) indices — the `incompleteBars` equivalent. Reuses `getHatchPattern`, resolving per-bar color via `barColorAt`.
- **Gap 3 closed by verification, not code**: `onDateRangeZoom` resolves drags purely against label positions and an existing BarChart test already drags across categorical labels. Documented as label-generic in the charts AGENTS.md; do not add a duplicate test.

The PR went through the sp-swarm/sp-triage review loop: all threads resolved except one deferred (see below); the review-fix commit is `e1d832ba`.

### Decisions made (and why)

- **Hatch look**: reused the package's existing `getHatchPattern` (same treatment as `stroke.partial` dashed bars) instead of porting the legacy faded-fill pattern from `createHashedPattern` — one consistent "not final" visual across the package. Revisit during the heavy wave if LogsViewerSparkline needs the faded look.
- **HighlightedRange vs drag-select band**: intentionally separate. The canvas drag band (`drawSelectionRect`, blue) is transient gesture feedback; `HighlightedRange` (DOM, neutral gray) is persistent externally-controlled state (e.g. mirroring a virtualized list's visible rows). They share ~3 lines of clamp math — do not unify the rendering. If design wants visual coherence later, the right seam is a `--color-graph-selection-*` token (noted in a comment above `SELECTION_FILL` in `canvas-renderer.ts`).

### Known gaps / deferred items

- **ComboChart has no `scales.extent`**, so `HighlightedRange` falls back to point-to-point on combo bar series instead of covering bands. Real gap, needs a ComboChart design decision — left as an open review thread on #70223. Only matters if a combo-chart consumer ever needs the overlay.
- Follow-ups acknowledged in resolved review threads on #70223: default the overlay color to `theme.crosshairColor ?? '#8f8f8f'`; set explicit `boxSizing: 'border-box'` on the border div; add a test pinning that a hatched bar with a `bars[i].color` override hatches in the override color.

### Environment notes for the next agent

- **Running quill charts tests**: they run under `frontend/jest.config.ts` (its `roots` include `packages/quill/packages/*/src`). `hogli test <charts path>` misroutes to a package-local jest with no TS transform and fails with `SyntaxError` — use `cd frontend && pnpm exec jest --config jest.config.ts ../packages/quill/packages/charts/src/...` instead (devex feedback filed).
- Fresh checkouts need `pnpm install --filter @posthog/frontend... --frozen-lockfile` before tests run.
- The full `typescript:check` fails in fresh checkouts (missing kea typegen artifacts, thousands of pre-existing errors) — verify charts changes with the package-local `tsc -p tsconfig.json` (test files show known jest-types noise; source files should be clean) and let CI do the rest.
- Format with `bin/hogli format:js <files>`; there is no prettier setup inside `packages/quill`.

### Next up

PR 2 per the sequence above: the in-place quill rendering path in `lib/components/Sparkline.tsx` behind a feature flag, covering the simple wave. Wait for #70223 to merge rather than stacking on it. The wrapper will need the semantic-color shim (gap 4 — app-side, `getColorVar`-based) since quill takes CSS colors while legacy consumers pass names like `'success'`/`'danger'`/`'muted'`.

## Handover — status after step 2 (2026-07-11)

### Done

Step 2 (in-place quill path behind a flag) is up as [#70231](https://github.com/PostHog/posthog/pull/70231), based on master (not stacked on #70223 — the simple wave needs none of its new capabilities):

- **Quill's own `Sparkline` component is the rendering target** (Sam's review call — the first cut hand-configured compact `BarChart`/`LineChart` in the app instead). The package component was extended for this: stacked-bar `type: 'bar'`, a `series` prop for multi-series with per-series control, and an opt-in `tooltip` render prop (off by default, as before). Existing package consumers (`MetricCard`, quill-components' `Metric`) unchanged; charts `AGENTS.md` row updated; 2 new package tests + 3 new package stories.
- App `Sparkline` dispatches at the top: `quill-sparkline` flag on + only simple props → `QuillSparkline`, a thin adapter that normalizes data/colors and renders the quill `Sparkline` with a `DefaultTooltip` render prop; otherwise `LegacySparkline` (the old component, renamed, untouched).
- The legacy-feature gate routes `onSelectionChange`, `highlightedRange`, non-empty `incompleteBars.indices`, non-empty `referenceLines`, and `withXScale`/`withYScale` to Chart.js — so every medium/heavy-wave consumer is unaffected even with the flag on. Riders on the flag: all simple-wave consumers, plus any HogQLX `<Sparkline>` tag using only simple props.
- Semantic-color shim (gap 4) landed inside the component: `resolveSparklineColor` passes CSS-looking values (`#…`, `rgb…`, `hsl…`, `var(…)`) through and resolves everything else via `getColorVar`.
- `normalizeSparklineData` extracted and shared by both paths, so the permissive `data` prop normalizes identically.
- Tests (`Sparkline.test.tsx`, 12) cover dispatch both ways, per-prop legacy fallback, series normalization, tooltip option wiring, loading skeleton. Stories: three quill-flagged variants alongside the legacy ones.

### Decisions made (and why)

- **`maximumIndicator` and `tooltipRowCutoff` are dropped on the quill path** (per the plan's "accept dropping it"): no max-tick-only axis mode in quill, and its tooltip scrolls past ~10 rows instead of cutting off. They do NOT route to legacy — the default `maximumIndicator: true` would have pinned nearly every consumer to Chart.js and made the flag a no-op.
- **Tooltip behavior difference to expect in visual review**: quill bar charts hit-test the cursor against filled segments (`BarTooltip.narrowSeriesByCursor`) — hovering the empty space above a short bar shows no tooltip, and hovering a stacked segment shows that segment only. Chart.js showed the whole column from anywhere in the band. Accepted as quill's app-wide interaction model.

### Environment/test gotchas discovered

- `featureFlagLogic`'s `featureFlags` reducer is kea-persisted to localStorage, which survives across jest tests in a file — always set the flag explicitly per test (true AND false), never rely on "unset means off".
- Quill charts render two canvases: the labelled main canvas (`aria-label="Chart with N data series"`) plus an aria-hidden hover-overlay canvas. A "legacy canvas" selector must exclude both attributes.
- The quill tooltip portal (`[data-hog-charts-tooltip]`) mounts before its content commits — wrap tooltip-content assertions in `waitFor` after `hoverUntilTooltip`.

### Next up

Step 3 (medium wave): time axes via `config.xAxis`, reference lines via quill `ReferenceLine`, drag-select via `onDateRangeZoom` — extending the quill path so InvocationsSparkline, LogsSamplingForm, and the metrics product stop hitting the legacy gate; delete `MetricsChartLegend` in favor of quill's `config.legend`. Wait for #70223 (HighlightedRange/hatch) to merge first — the heavy wave needs it, and the medium wave's drag-select verification should happen on top of it.
