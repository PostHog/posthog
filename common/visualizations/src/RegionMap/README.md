# RegionMap

Choropleth map of states/provinces for trends results broken down by region (ISO 3166-2 subdivision codes).
The sub-national counterpart to `WorldMap`, shading each subdivision proportionally to its value.

## Exports

- `RegionMap` (`RegionMap.tsx`, re-exported from `index.ts`) — takes `ChartParams` (`showPersonsModal`, `context: QueryContext`).
  Geometry is loaded at runtime from a Natural Earth topojson file served at `/static/geo/ne_10m_admin_1_states_provinces.json`.
  Hovering a region renders an `InsightTooltip` with the country flag, subdivision name, and aggregated value; clicking opens the persons modal.
- `regionMapLogic` (`regionMapLogic.tsx`) — kea logic tracking the hovered subdivision and tooltip coordinates, keyed by `InsightLogicProps`.

## Dependencies

Built on `react-simple-maps` (`ComposableMap`, `Geographies`, `Geography`) — SVG rendering, no Chart.js plugins.
Tooltips go through `useInsightTooltip` from `../InsightTooltip`.

## Consumers

- `common/query-frontend/src/nodes/TrendsQuery/Trends.tsx` — trends insights with the region map display type (requires a region breakdown)

## Known debt

`RegionMap` reads from `insightLogic`, `regionMapLogic`, `teamLogic`, and `groupsModel`, and formats values via query-frontend helpers.
New chart components should be props-driven instead (see the package README).
