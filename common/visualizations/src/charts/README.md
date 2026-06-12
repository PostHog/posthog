# charts

Chart-agnostic building blocks shared by chart components: theme and axis-format types, value formatting, theme construction, and CSS variable color resolution.
Everything here is pure (no React components, no kea logics).

## Exports

- `types.ts`
  - `AxisFormat` — `'number' | 'compact' | 'percent' | 'duration' | 'duration_ms' | 'date' | 'datetime' | 'none'`
  - `ChartTheme` — `{ colors, backgroundColor?, axisColor?, gridColor?, crosshairColor?, tooltipBackground?, tooltipColor?, tooltipZIndex? }`; `backgroundColor` is required by radial charts for the pie hover pop-out mask
- `utils/format.ts`
  - `formatValue(value, format, options?)` — formats a number per `AxisFormat` with optional `prefix`, `suffix`, and `decimalPlaces` (compact `1.2K/3.4M/5.6B` notation, durations, dates, percentages)
- `utils/theme.ts`
  - `buildTheme(overrides?)` — builds a `ChartTheme` from the current CSS theme (`lib/colors` palettes plus computed `--color-bg-surface-primary`)
  - `seriesColor(theme, index)` — palette color with wraparound
- `utils/color.ts`
  - `resolveVariableColor(color)` — resolves `var(--x)` CSS custom properties to computed color strings, cached; plain colors pass through

## Chart.js plugins

None — these are plain TypeScript utilities.
`resolveVariableColor` exists because Chart.js canvases can't consume CSS variables directly.

## Consumers

- `products/product_analytics/frontend/insights/` — the trends, funnels, retention, and stickiness chart implementations (theme + formatting)
- `common/query-frontend/src/nodes/DataVisualization/Components/Charts/LineGraph.tsx` — SQL insight charts
- `products/mcp_analytics/frontend/` and `products/replay_vision/frontend/` — dashboard cards and scanner overview
- `../LineGraph/LineGraph.tsx` — uses `resolveVariableColor` for dataset colors

New chart components should source their colors and value formatting from here rather than reaching into `scenes/` or query-frontend helpers.
