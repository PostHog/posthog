# Histogram

D3-based histogram with animated bars, used for funnel time-to-convert distributions.
This is the one chart in the package rendered with d3 instead of Chart.js.

## Exports

- `Histogram` (`Histogram.tsx`, re-exported from `index.tsx`) — props (`HistogramProps`):
  - `data: HistogramDatum[]` — `{ id, bin0, bin1, count, label }` per bin; bin values of `-2`/`-1` are rendered as `<x` / `>=x` outlier buckets
  - `layout?: FunnelLayout` — vertical (default) or horizontal
  - `isAnimated?`, `isDashboardItem?`, `width?`, `height?`
  - `formatXTickLabel?`, `formatYTickLabel?` — tick formatters
- `HistogramDatum` — the bin shape above.
- `histogramLogic` (`histogramLogic.ts`) — kea logic holding the layout-dependent d3 config (scales, ranges, transforms).
- `histogramUtils.ts` — `HistogramConfig`, `INITIAL_CONFIG`, `getConfig(layout, width, height)`, `createRoundedRectPath`, `D3HistogramDatum`.

## Chart.js plugins

None — rendering is pure d3 (`d3.scaleLinear`, axis generators, SVG paths) via the `useD3` hook and helpers from `lib/d3/utils`.

## Consumers

- `common/query-frontend/src/nodes/FunnelsQuery/FunnelHistogram.tsx` — funnel time-to-convert view (`FunnelsQuery` with `funnelVizType: time_to_convert`)
- `frontend/src/lib/d3/utils.ts` — type-level import for shared d3 helpers

## Known debt

`Histogram` reads theming from `insightLogic` / `insightVizDataLogic` and layout config from the singleton `histogramLogic`.
New chart components should take theme and config via props instead (see the package README).
