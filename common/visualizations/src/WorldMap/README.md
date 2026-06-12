# WorldMap

Choropleth world map for trends results broken down by country.
Each country is shaded proportionally to its value (with a saturation floor of 0.2 so small values stay visible).

## Exports

- `WorldMap` (`WorldMap.tsx`, re-exported from `index.ts`) — takes `ChartParams` (`showPersonsModal`, `context: QueryContext`).
  Series and tooltip state come from `worldMapLogic`; hovering a country renders an `InsightTooltip` with the country flag, name, and aggregated value, and clicking opens the persons modal.
- `worldMapLogic` (`worldMapLogic.tsx`) — kea logic tracking the hovered country and tooltip coordinates, keyed by `InsightLogicProps`.
- `countryVectors` (`countryVectors.tsx`) — `Record<string, JSX.Element>` of hand-rolled SVG `<path>` elements per ISO country code; this is the map itself.

## Chart.js plugins

None — the map is a static inline SVG built from `countryVectors`, no canvas or Chart.js involved.
Tooltips go through `useInsightTooltip` from `../InsightTooltip`.

## Consumers

- `common/query-frontend/src/nodes/TrendsQuery/Trends.tsx` — trends insights with the world map display type (requires a country code breakdown)
- `frontend/src/scenes/web-analytics/LiveMetricsDashboard/LiveWorldMap.tsx` — live web analytics metrics map

## Known debt

`WorldMap` reads from `insightLogic`, `worldMapLogic`, `teamLogic`, and `groupsModel`, and formats values via query-frontend helpers.
New chart components should be props-driven instead (see the package README).
