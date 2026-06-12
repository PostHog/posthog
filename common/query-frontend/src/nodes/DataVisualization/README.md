# DataVisualization

Renders a `DataVisualizationNode` — the SQL insight visualization node.
It takes a `HogQLQuery` source and displays the result as a chart or a formatted table, with an optional side bar (in edit mode) for configuring series, display settings, and conditional formatting.
This is what powers SQL insights and the visualization pane of the SQL editor.
Data fetching is delegated to `dataNodeLogic` (see `../DataNode`); this folder owns chart configuration and rendering.

## Usage

```tsx
import { Query } from '@posthog/query-frontend/Query/Query'

<Query
    query={{
        kind: 'DataVisualizationNode',
        source: {
            kind: 'HogQLQuery',
            query: `select toDate(timestamp) as timestamp, count()
                    from events
                    where timestamp >= now() - interval '7 days'
                    group by timestamp
                    order by timestamp asc`,
        },
        display: 'ActionsLineGraph',
    }}
    setQuery={(query) => {...}}
/>
```

The schema (`DataVisualizationNode` in `src/schema/schema-general.ts`) adds `display` (`ChartDisplayType`), `chartSettings` (axes, goal lines, stacking, y-axis scale, ...), and `tableSettings` (per-column formatting, conditional formatting rules) on top of the `source` query.
See `src/examples.ts` (`DataVisualization`, `DataWarehouse`) for full examples.

## Key files and logics

- `DataVisualization.tsx` — exports `DataTableVisualization`, which wires up the logics, the toolbar (table/chart picker, date range, reload, export), variables, and the side bar
- `dataVisualizationLogic.ts` — central state: visualization type, selected x/y series, columns and their inferred types, chart and table settings
- `displayLogic.ts` — goal lines and display-tab state
- `queryUpdateUtils.ts` — `applyDataVisualizationQueryUpdate`, functional `setQuery` updates that don't clobber concurrent source edits
- `types.ts` — column scalar types and formatting templates

The kea logics are internal to the `<Query />` tag — consumers interact via the `query` / `setQuery` props only.

## Components

Under `Components/`:

- `Charts/LineGraph.tsx` (+ `lineGraphLogic.ts`) and `Charts/PieChart.tsx` — Chart.js renderers for line, bar, area, and pie displays
- `Heatmap/TwoDimensionalHeatmap.tsx` — heatmap display
- `Table.tsx` — formatted result table (used for the table display and alongside charts)
- `TableDisplay.tsx` — the chart-type dropdown
- `SideBar.tsx` with `SeriesTab.tsx`, `DisplayTab.tsx`, and `ConditionalFormatting/` (+ `conditionalFormattingLogic.ts`) — edit-mode configuration panel
- `seriesBreakdownLogic.ts` / `ySeriesLogic.ts` — series selection and breakdown handling
- `Variables/` — query variables: `variablesLogic`, `variableModalLogic`, `VariablesForInsight`, `AddVariableButton`, `NewVariableModal` (insert `{variables.foo}` placeholders into the SQL and edit their values)

A bold-number display and empty/error states are shared with insights (`@posthog/visualizations`, `../InsightViz/EmptyStates`).
