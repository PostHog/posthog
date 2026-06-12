# InsightTooltip

The shared tooltip used by every insight chart: a table of series rows (color, label, value) with an optional date header, breakdown columns, and a "click to view people" hint.
Also home to `useInsightTooltip`, the singleton manager that owns the tooltip DOM.

## Exports

- `InsightTooltip` (`InsightTooltip.tsx`) — props (`InsightTooltipProps`): `seriesData: SeriesDatum[]`, `date`, `timezone`, `renderSeries`/`renderCount` (custom cell renderers), `altTitle`/`altRightTitle`, `breakdownFilter`, `interval`, `dateRange`, `rowCutoff`/`colCutoff`, `embedded`, `hideColorCol`, `hideInspectActorsSection`, `groupTypeLabel`, `showHeader`, `onClose`, `onRowClick`.
  Switches to a column-per-entity layout when multiple entities are combined with a breakdown or compare.
- `ClickToInspectActors` — the footer hint block.
- `useInsightTooltip` (`useInsightTooltip.ts`) — hook returning `{ getTooltip, showTooltip, hideTooltip, positionTooltip, positionTooltipAt, resetTooltipPosition, measureTooltip, cleanupTooltip, pinTooltip }`.
  It manages two shared `document.body`-level elements (one hover tooltip, one pinned tooltip) with React roots, ownership tracking per caller, hide/interactivity timers, viewport clamping, and global scroll/click/Escape listeners for unpinning.
  Module-level functions (`ensureTooltip`, `pinTooltip`, `unpinTooltip`, `positionTooltip`, …) are also exported for non-hook callers.
- `insightTooltipUtils.tsx` — `SeriesDatum`, `InvertedSeriesDatum`, `TooltipConfig`, `InsightTooltipProps`, `getTooltipTitle`, `getFormattedDate`, `getDatumTitle`, `invertDataSource`, `INTERVAL_UNIT_TO_DAYJS_FORMAT`.

## Chart.js plugins

None — the tooltip is plain React rendered into a shared DOM element.
Chart.js components feed it data by converting `TooltipItem[]` via `createTooltipData` from `../LineGraph/tooltip-data`.

## Consumers

Used internally by `LineGraph`, `PieChart`, `BoldNumber`, `BoxPlot`, `WorldMap`, and `RegionMap`, and externally by:

- `products/product_analytics/frontend/insights/` — trends, funnels, retention, and stickiness chart implementations
- `common/query-frontend/src/nodes/FunnelsQuery/` and `DataVisualization/Components/Charts/LineGraph.tsx`
- `frontend/src/scenes/experiments/charts/funnel/FunnelTooltip.tsx`

## Known debt

`InsightTooltip` reads from `teamLogic` and `propertyDefinitionsModel` for value formatting.
The component is otherwise props-driven, which is the direction the rest of the package should follow.
