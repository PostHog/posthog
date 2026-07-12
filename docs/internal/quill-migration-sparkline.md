# Work stream: replace the shared Chart.js Sparkline with quill

Goal: delete `frontend/src/lib/components/Sparkline.tsx` (Chart.js + `chartjs-plugin-annotation`, ~520 lines) and move all ~18 consumers to `@posthog/quill-charts`.
Part of the chart.js removal effort — see [quill-chart-migration.md](./quill-chart-migration.md).

## Key insight — it is two migrations, not one

The shared `Sparkline` has grown into two different things wearing one name, and they map onto two different quill primitives. Treating them as one is what produced the long `needsLegacyFeatures` gate.

- **True sparklines** — small, axis-less, inline. May be multi-series stacked bars with a hover tooltip, but no axis, no selection, no reference lines. These map onto the quill `Sparkline` preset (deliberately minimal: `hideXAxis` / `hideYAxis` always on).
- **Charts in disguise** — interactive time-series bar charts built on the `Sparkline` component. They pull in brushing, custom scales, reference lines, highlighted ranges, incomplete-bar hatching. These are not sparklines and should migrate to quill's `TimeSeriesBarChart` (plus overlays and the drag interaction), not through the `Sparkline` component at all.

The divider is **chart features, not multi-series**. A stacked-bar sparkline like `AppMetricsSparkline` (success/failure, no axes) is still a true sparkline. What makes something population B is the presence of `onSelectionChange`, `withXScale` / `withYScale`, `referenceLines`, `highlightedRange`, or `incompleteBars`.

An earlier framing in this doc said "quill's `Sparkline` is NOT the target, most consumers need compact `BarChart`." That was superseded: quill's `Sparkline` was extended (#70236: bars, multi-series, opt-in tooltip) and IS the target for population A, including bar sparklines. Population B is the part that goes to `TimeSeriesBarChart`.

## `needsLegacyFeatures` is a "this is not a sparkline" detector

The gate in `Sparkline.tsx` routes a consumer to the legacy Chart.js path when it uses a feature the quill `Sparkline` preset does not (and should not) implement. Read it as a population-B detector, not as a list of unported sparkline features. The endgame is an empty gate: once every population-B consumer has moved to `TimeSeriesBarChart` and every population-A consumer renders via quill, `LegacySparkline` has no callers and gets deleted along with the `quill-sparkline` flag.

## Legacy feature surface

From `frontend/src/lib/components/Sparkline.tsx`:

- `data: number[] | SparklineTimeSeries[]` — multi-series, always **stacked** when multiple
- `type: 'bar' | 'line'` (default bar — most consumers use bars)
- `onSelectionChange({startIndex, endIndex})` — drag-to-select with in-progress overlay + Escape cancel
- `highlightedRange` — persistent translucent box mirroring an external range (annotation plugin). NOT drag-driven: in `LogsViewerSparkline` it mirrors the scrolled visible-row window
- `incompleteBars` — diagonal-hatch pattern on given bar indices + warning row in tooltip
- `referenceLines` — dashed horizontal threshold lines with labels; y-axis auto-expands with headroom
- `withXScale` / `withYScale` — raw Chart.js scale escape hatches (time axes, category axes, hiding axes)
- Tooltip options: `renderLabel`, `renderTooltipValue`, `tooltipRowCutoff`, `hideZerosInTooltip`, `sortTooltipByCount`
- `maximumIndicator` — y-axis showing only the max tick
- Semantic color names (`'success'`, `'danger'`, `'muted'`) resolved via `getColorVar`
- `loading` → `LemonSkeleton`

## Consumer inventory (18 files)

### Population A — true sparklines (→ quill `Sparkline`, this migration)

- `frontend/src/lib/components/AppMetrics/AppMetricsSparkline.tsx` — two-series stacked bars (success/failure)
- `frontend/src/queries/nodes/HogQLX/render.tsx` — HogQLX `<Sparkline>` tag; migrate **last**, screenshot-test it
- `frontend/src/scenes/data-management/ingestion-warnings/IngestionWarningsView.tsx` (v1) — flat-array bars
- `frontend/src/scenes/data-management/ingestion-warnings-v2/IngestionWarningsV2View.tsx` (v2)
- `frontend/src/scenes/hog-functions/metrics/HogFunctionEventEstimates.tsx` — single bar series
- `products/ai_gateway/frontend/gatewayUsage.tsx` — single bar series, currency `renderTooltipValue`, `loading`
- `products/engineering_analytics/frontend/components/TrendCard.tsx` — sentiment-colored line; `Sparkline` or `MetricCard` fits 1:1
- `products/links/frontend/LinkMetricSparkline.tsx` — single-series bars, `loading`
- `products/logs/frontend/components/LogsPatterns/LogsPatterns.tsx` — in-table trend cells
- `products/logs/frontend/components/LogsServices/LogsServices.tsx` — in-table trend cells

### Population B — charts in disguise (→ quill `TimeSeriesBarChart`, separate work)

| File | Chart features it uses |
| --- | --- |
| `products/logs/frontend/components/LogsViewer/LogsViewerSparkline/index.tsx` | onSelectionChange, highlightedRange, incompleteBars, withXScale, tooltipRowCutoff |
| `products/tracing/frontend/TracingSparkline.tsx` | onSelectionChange, highlightedRange, withXScale, tooltipRowCutoff (dual mode: volume vs duration histogram) |
| `products/tracing/frontend/OperationHistogram.tsx` | onSelectionChange, highlightedRange, withXScale, tooltipRowCutoff (log-spaced duration buckets) |
| `frontend/src/scenes/hog-functions/invocations/InvocationsSparkline.tsx` | onSelectionChange, withXScale |
| `products/metrics/frontend/components/MetricsSeriesChart.tsx` | withXScale (target `TimeSeriesLineChart` + `config.legend`; delete `MetricsChartLegend`) |
| `products/metrics/frontend/components/MetricsViewer.tsx` | withXScale |
| `products/customer_analytics/frontend/components/UsageMetricCard.tsx` | withXScale, withYScale (borderline — small stat card; consider quill `MetricCard` wholesale, or confirm the scale tweaks can drop) |
| `products/logs/frontend/components/LogsSampling/LogsSamplingForm.tsx` | referenceLines |

Type-only importers (`SparklineTimeSeries`): `logsAlertDetailSceneLogic.ts`, `metricsViewerLogic.tsx`, `MetricsChartLegend.tsx` — update the import path.

Not consumers (do not touch): `engineering_analytics` `FailureSparkline` / `PushHistorySparkline` (raw SVG) and `error_tracking` `VolumeSparkline` (D3) are independent implementations.

## Quill capabilities

- **`Sparkline` preset** — minimal, axis-less, multi-series stacked bars + opt-in tooltip (extended in #70236). Serves population A. Keep.
- **`TimeSeriesBarChart` / `TimeSeriesLineChart` / `ComboChart`**, `ReferenceLine` overlay, and the drag interaction (`useDragToZoom` / `onDateRangeZoom`, which **pre-existed** in quill — not added by this effort). This is the machinery population B needs.
- **`HighlightedRange` overlay + per-bar hatch fill** — built in #70223 as a step-1 "close the gap" for population B, then **reverted in [#70252](https://github.com/PostHog/posthog/pull/70252)** because nothing rendered them (population B had not migrated yet and the reframe pushed that work out). Rebuild them during the population-B migration, against the real `TimeSeriesBarChart` requirements. Note #70223 also left an open `ComboChart` `scales.extent` gap, so the shape was not settled — rebuilding later is the more honest path than carrying unused public API.

## Decisions

- **`maximumIndicator` — dropped on the quill path, not gated.** The quill sparkline is axis-less and shows no y-axis peak label. About 11 population-A consumers rely on the default `true` and lose that label; that is accepted (it "kinda sucks" as a default, and a bare sparkline is cleaner). It deliberately does **not** route to legacy: gating on `maximumIndicator !== false` would pin nearly every consumer to Chart.js and make the flag a no-op. The 6 consumers that pass `maximumIndicator={false}` are unaffected either way.
- **`tooltipRowCutoff` — drop, do not port.** A defensive cap at 100 tooltip rows. The three population-B consumers that set it break down into a handful of series, so it never fires in practice. Do not pass it when they move to `TimeSeriesBarChart`; add a cap to the chart tooltip later only if a genuinely high-cardinality surface appears.
- **`hoverColor` — unused across the app. Drop.**

## Recommended approach

Refactor `lib/components/Sparkline.tsx` **in place**: keep the existing prop surface, dispatch to quill vs legacy behind the `quill-sparkline` flag. This gives one dispatch point and zero consumer churn during rollout.
`withXScale` / `withYScale` are Chart.js-specific escape hatches — do not try to support them generically; population B consumers translate them to their `TimeSeriesBarChart`'s structured scale config as they migrate.

## PR sequence

1. ~~Quill capability PR: `HighlightedRange` overlay, per-bar hatch~~ — done as #70223, then **reverted (#70252)** as unused. Rebuild during step 4.
2. In-place quill rendering path in `Sparkline.tsx` behind the flag, covering population A — up as [#70231](https://github.com/PostHog/posthog/pull/70231). Extends quill's `Sparkline` (#70236).
3. Migrate population-A consumers (verify each): links, ai_gateway, ingestion warnings, hog functions, engineering analytics `TrendCard`, logs patterns/services. HogQLX tag last, with screenshot coverage.
4. **Population B → `TimeSeriesBarChart`, one product surface at a time** (Logs, Tracing, Metrics, Invocations, LogsSamplingForm). This replaces the earlier plan of extending the `Sparkline` path to keep them off the legacy gate — **do not** extend `Sparkline` for them; move them out to the real chart type, where the drag interaction lives and where `HighlightedRange` / hatch / `ReferenceLine` get (re)built. Delete `MetricsChartLegend` in favor of quill's `config.legend`.
5. Cleanup: delete the flag, `needsLegacyFeatures`, and `LegacySparkline`; update `Sparkline.stories.tsx`; drop `chartjs-plugin-annotation` (coordinate with `products/alerts`, which also registers it).

## Testing

The legacy component had stories only and no unit tests. #70231 added `Sparkline.test.tsx` (dispatch both ways, per-prop legacy fallback, series normalization, tooltip wiring, loading skeleton). For the population-B migrations, test through `@posthog/quill-charts/testing` (`getHogChart`, tooltip accessors): stacked multi-series, drag-select index reporting, reference-line placement, highlighted range. Invoke `/writing-tests`; parameterize repeated variations.

## Handover — status after step 1 (2026-07-11)

### Done

Step 1 (quill capability PR) merged as [#70223](https://github.com/PostHog/posthog/pull/70223):

- **`HighlightedRange` overlay** — `start`/`end` accept data indices or labels; band-aware via `scales.extent`; clamps to the plot area. Testing hook `data-attr="hog-chart-highlighted-range"`.
- **Per-bar hatch**: `Series.bars[i].hatch` hatches individual bars at arbitrary indices — the `incompleteBars` equivalent.
- **Gap closed by verification, not code**: `onDateRangeZoom` resolves drags purely against label positions and already handles categorical labels.

> **Superseded — see the step-3 reframe handover below.** Both capabilities from #70223 were reverted in [#70252](https://github.com/PostHog/posthog/pull/70252) as unused. They are step-4 work now.

### Decisions made (and why)

- **HighlightedRange vs drag-select band**: intentionally separate. The canvas drag band (`drawSelectionRect`, blue) is transient gesture feedback; `HighlightedRange` (DOM, neutral gray) is persistent externally-controlled state (e.g. mirroring a virtualized list's visible rows). Do not unify the rendering.

### Environment notes for the next agent

- **Running quill charts tests**: they run under `frontend/jest.config.ts`. `hogli test <charts path>` misroutes to a package-local jest and fails with `SyntaxError` — use `cd frontend && pnpm exec jest --config jest.config.ts ../packages/quill/packages/charts/src/...`.
- Fresh checkouts need `pnpm install --filter @posthog/frontend... --frozen-lockfile` before tests run.
- Full `typescript:check` fails in fresh checkouts (missing kea typegen); verify charts changes with the package-local `tsc -p tsconfig.json` and let CI do the rest.
- Format with `bin/hogli format:js <files>`; no prettier setup inside `packages/quill`.

## Handover — status after step 2 (2026-07-11)

### Done

Step 2 (in-place quill path behind a flag) is up as [#70231](https://github.com/PostHog/posthog/pull/70231), based on master:

- **Quill's own `Sparkline` is the rendering target** (the first cut hand-configured compact `BarChart`/`LineChart` instead). The package component was extended (#70236): stacked-bar `type: 'bar'`, a `series` prop, and an opt-in `tooltip` render prop (off by default). Existing package consumers (`MetricCard`, quill-components' `Metric`) unchanged.
- App `Sparkline` dispatches at the top: `quill-sparkline` flag on + only simple props → `QuillSparkline`; otherwise `LegacySparkline` (old component, renamed, untouched).
- The `needsLegacyFeatures` gate routes `onSelectionChange`, `highlightedRange`, non-empty `incompleteBars.indices`, non-empty `referenceLines`, and `withXScale`/`withYScale` to Chart.js — so every population-B consumer is unaffected even with the flag on.
- Semantic-color shim: `resolveSparklineColor` passes CSS-looking values through and resolves names via `getColorVar`. `normalizeSparklineData` extracted and shared by both paths.
- `Sparkline.test.tsx` (12 tests) + three quill-flagged stories.

### Decisions / gotchas

- **`maximumIndicator` and `tooltipRowCutoff` dropped on the quill path** (see Decisions above).
- **Tooltip behavior difference**: quill bar charts hit-test the cursor against filled segments — hovering empty space above a short bar shows no tooltip, and a stacked segment shows that segment only. Chart.js showed the whole column. Accepted as quill's interaction model.
- `featureFlagLogic`'s `featureFlags` reducer is kea-persisted to localStorage and survives across jest tests in a file — set the flag explicitly per test (true AND false).
- Quill renders two canvases (labelled main + aria-hidden hover overlay); a "legacy canvas" selector must exclude both attributes.
- The quill tooltip portal mounts before its content commits — wrap tooltip assertions in `waitFor` after `hoverUntilTooltip`.

## Handover — reframe + revert (2026-07-11)

### What changed in the plan

Reviewing #70231 surfaced the **two-population** framing at the top of this doc. The consequences:

- The medium/heavy consumers (Logs, Tracing, Metrics, Invocations, LogsSamplingForm) are **not sparklines** — they are interactive time-series bar charts. The plan's old step 3 ("extend the quill `Sparkline` path so they stop hitting the legacy gate") was the wrong direction. They now migrate to `TimeSeriesBarChart` (step 4 above) and exit the `Sparkline` component entirely.
- `needsLegacyFeatures` is therefore correct as-is — it is the population-B detector, and it goes empty only when population B has moved to `TimeSeriesBarChart`.

### The revert (#70252)

The step-1 capabilities (`HighlightedRange` overlay, per-bar hatch) had **zero live consumers**: nothing in `frontend/` or `products/` imports the overlay or sets `bars[i].hatch`, and the app's `highlightedRange` usages all flow through the legacy Chart.js `Sparkline`. They were speculative infra for a population-B migration that has not started. Reverted in [#70252](https://github.com/PostHog/posthog/pull/70252) — clean inverse, no dangling references, pre-existing hatch machinery (`stroke.partial` dashes, `bars.track`) untouched. Rebuild during step 4 with the real requirements (and resolve the `ComboChart` `scales.extent` gap then).

#70236 (Sparkline bar/series/tooltip) was **kept** — #70231 consumes it for population-A bar sparklines.

### Next up

Step 3: migrate the population-A consumers behind the flag and verify each. Then step 4: population B → `TimeSeriesBarChart`, rebuilding `HighlightedRange` / hatch as that work needs them.
