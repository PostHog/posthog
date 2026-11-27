# Composing the primitives in another product

Read this before you put a dashboard, a tile or a filter bar on another product's page.
Paths are relative to `products/dashboards_v2/frontend/`.
`scene/DashboardScene.tsx` is the full example of a host, with saving, filters and real queries.

## The parts a host supplies

| Part                | What it is                                                         | Where it comes from                                              |
| ------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------- |
| The document        | A `Dashboard` as JSON (`dashboard/document/dashboardSchema.ts`)    | Your own code, a fixture, a saved board or a URL                 |
| The panel types     | `PanelType[]`, such as `createChartPanel(...)` and `markdownPanel` | Built in, or your own through `/adding-dashboard-v2-panel-types` |
| The query runner    | A `RunQuery` (`query/queryTypes.ts`) that returns `DataFrame`s     | Your product, passed to `createChartPanel({ runQuery })`         |
| State and callbacks | `onEdit`, `activeTabId`, `filters`, `timeRange`, `history`         | Leave out any of them that you do not need                       |

Keep `dashboard`, `panels`, `filters` and `timeRange` the same between renders, such as module constants or `useMemo` values.
A new one re-renders every tile.

## A read-only dashboard from JSON

A product that only gives a JSON document gets a dashboard with tabs, a grid and charts.
Nothing loads it from a board, and nothing saves it.

```tsx
import { DashboardView } from 'products/dashboards_v2/frontend/dashboard/core/DashboardView'
import { dashboardFromJson } from 'products/dashboards_v2/frontend/dashboard/document/dashboardFromJson'
import { createChartPanel } from 'products/dashboards_v2/frontend/panels/chart/createChartPanel'
import { markdownPanel } from 'products/dashboards_v2/frontend/panels/markdown/markdownSpec'

const PANELS = [createChartPanel({ runQuery: runMyQuery }), markdownPanel]

const MY_DASHBOARD = {
  version: 2,
  title: 'Service health',
  time: { from: 'now-24h', to: 'now' },
  tabs: [
    {
      id: 'overview',
      title: 'Overview',
      tiles: [
        {
          id: 'requests',
          place: { x: 0, y: 0, w: 16, h: 14 },
          panel: {
            type: 'chart',
            title: 'Requests',
            config: {
              query: { language: 'hogql', query: 'select toStartOfHour(timestamp), count() from events group by 1' },
              viz: { type: 'line' },
            },
          },
        },
        {
          id: 'note',
          place: { x: 16, y: 0, w: 8, h: 14 },
          panel: { type: 'markdown', config: { text: 'Alerts page at 1% errors.' } },
        },
      ],
    },
  ],
}

const { dashboard, problems } = dashboardFromJson(MY_DASHBOARD, PANELS)

export function ServiceHealth(): JSX.Element | null {
  return dashboard && <DashboardView dashboard={dashboard} panels={PANELS} surface="my-product" />
}
```

- The grid is 24 columns wide. `place` is in grid cells.
- `dashboard` is null only when the JSON does not have the shape of a dashboard. A panel that fails its own type's check still renders, and its tile says why.
- `problems` lists each problem with its `path`, such as `tabs[0].tiles[1].panel.config.query`. Assert it is empty in a test of your JSON, so a typo fails CI instead of showing a broken tile.
- `query.language` is `hogql`, `query` (a `QuerySchema` node), `promql` or `logql`. Your runner decides which languages it runs.
- With no `runQuery`, nothing runs. `createChartPanel({ sampleData: true })` draws made-up data, for a story or an empty project.

## Run your own queries

A runner gets the panel's query, the time range around it and the filters with a value, and returns frames.
The dashboard never fetches data itself.

```tsx
const runMyQuery: RunQuery = async ({ query, time, filters }, signal) => {
  const rows = await fetchMyMetrics(query, time, filters, { signal })
  return {
    frames: [
      {
        name: 'Requests',
        fields: [
          { name: 'time', type: 'time', values: rows.map((row) => row.ts) },
          { name: 'count', type: 'number', values: rows.map((row) => row.count) },
        ],
      },
    ],
  }
}
```

Reject with an `AbortError` once `signal` aborts. Set `fetchedAt` when your result can come from a cache, so the tile can show how fresh it is.

## An editable dashboard that is not saved

Pass `onEdit` and the dashboard can be arranged. Keep the result in React state, and save it only if your product wants to.

```tsx
const SIZE_OF = sizeOfPanels(PANELS)

function MyEditableDashboard({ initial }: { initial: Dashboard }): JSX.Element {
  const { dashboard, record, undo, redo, canUndo, canRedo } = useDashboardHistory(initial)
  return (
    <DashboardView
      dashboard={dashboard}
      panels={PANELS}
      onEdit={(edit, view) => record(applyEdit(dashboard, edit, SIZE_OF, view))}
      history={{ canUndo, canRedo, onUndo: undo, onRedo: redo }}
      surface="my-product"
    />
  )
}
```

To save, write `dashboard` wherever your product keeps it. `dashboard/saved/savedDashboardLogic.ts` is one way to save it as a board, not a requirement.

## Filters and the time range

`useDashboardFilters` gives the controllers for a filter bar and a time range picker. Pass only the ones you want.

```tsx
const { filters, timeRange } = useDashboardFilters({ types: MY_FILTER_TYPES, time: { timezone } })
return (
  <DashboardView dashboard={dashboard} panels={PANELS} filters={filters} timeRange={timeRange} surface="my-product" />
)
```

With no `filters`, `timeRange`, `refresh` or `history`, the dashboard shows no filter bar, picker, refresh button or undo.
With no `onEdit`, it is read-only. With no `onActiveTabChange`, it keeps the shown tab itself.

## One panel on a page

Render `ContentTile` (`tiles/core/ContentTile.tsx`) with one panel and the panel types that can draw it.
No dashboard, grid or controller is needed.

```tsx
const PANELS = [createChartPanel({ runQuery: runMyQuery })]

const errorRate = {
    type: 'chart',
    title: 'Error rate',
    config: { query: { language: 'hogql', query: 'select ...' }, viz: { type: 'metric', options: { format: 'percentage' } } },
}

<FiltersContext.Provider value={{ time: { from: 'now-7d', to: 'now' }, filters: [] }}>
    <ContentTile panel={errorRate} panels={PANELS} />
</FiltersContext.Provider>
```

- Wrap it in `FiltersContext` only to give a time range or filters. Without it, the query runs on the range saved in it.
- Wrap it in `PanelHostContext` only to pass a refresh count down.
- A tile menu takes `actions` for what the tile does to itself. A tile on its own leaves out `placementActions`, which move or remove it in a grid.

## Your own kind of chart

A chart's query and its drawing are separate: `config.viz.type` picks a kind of chart, and every kind draws the same `DataFrame`s.
Add a kind when your product needs a chart no built-in kind draws, such as a heatmap with its own latency buckets. `DEFAULT_VIZ_TYPES` in `panels/chart/createChartPanel.tsx` lists the built-in kinds.
Add a panel type instead only when the content is not a query result, such as a list of traces with its own loading. Use `/adding-dashboard-v2-panel-types` for that.

Split the kind in two files, as `panels/chart/viz/metric/` does. The spec has no component, so code outside the browser can validate a document without loading React.

```ts
// latencyHeatmapSpec.ts
export const latencyHeatmapOptionsSchema = z.strictObject({
  buckets: z.int().positive().optional().describe('Buckets'),
})

export type LatencyHeatmapOptions = z.infer<typeof latencyHeatmapOptionsSchema>

export const latencyHeatmapSpec: VizSpec<LatencyHeatmapOptions> = {
  type: 'latency-heatmap',
  label: 'Latency heatmap',
  size: { w: 12, h: 12, minW: 6, minH: 6 },
  optionsSchema: latencyHeatmapOptionsSchema,
}
```

```tsx
// Load the drawing code the first time a tile draws this kind.
const LatencyHeatmap = lazyWithRetry(() => import('./LatencyHeatmap').then((m) => ({ default: m.LatencyHeatmap })))

const APM_PANELS = [
  createChartPanel({
    runQuery: runApmQuery,
    extraVizTypes: [defineViz({ ...latencyHeatmapSpec, Component: LatencyHeatmap })],
  }),
]
```

- `Component` gets `{ frames, options }` and only runs when there are rows to draw. Loading, empty and error come from the chart states.
- Set `Loading`, `Empty`, `Error`, `SampleData` or `isEmpty` on the kind to replace one state for it only. Pass `states` to `createChartPanel` to replace them for every built-in kind.
- An extra kind with the `type` of a built-in kind replaces it.
- `.describe('Label')` on an option sets its label in the chart options menu. Without it, the menu shows the capitalized key.
- A document that names a kind the host did not pass still loads, and its tile says the kind is unknown.

### Add to the chart menu

`menuActions` gets every chart's menu with the chart's own entries, and returns the menu to show.
Find an entry by its `key` (listed on `MenuAction` in `menu/menuAction.ts`) to remove or move it.

```tsx
createChartPanel({
  runQuery: runApmQuery,
  menuActions: (actions, { panel, disabledReason }) => [
    ...actions.filter((action) => action.key !== 'chart-type'),
    {
      key: 'open-in-traces',
      label: 'Open in traces',
      dataAttr: 'apm-open-in-traces',
      group: 'view',
      disabledReason: null,
      onSelect: () => router.actions.push(tracesUrlFor(panel.config)),
    },
  ],
})
```

Use `setConfig` from the second argument for an entry that changes the chart. It saves as one undo step. Pass the context's `disabledReason` on that entry, so it is disabled when the person cannot edit.

## Charts outside the app theme

Charts take their theme from the nearest quill `ChartThemeProvider`, or else from the quill CSS variables.
Wrap your page in `ChartThemeProvider` with the app theme (`useChartTheme` from `lib/charts/hooks`) to get the app's tooltip z-index above overlays.
