# Primitives

Read this before you write or review any file under `frontend/`.

A team picks only the primitives it wants and composes them anywhere, the way it uses Quill components.
A design is right when any product can take one primitive and use it without the others.

## Primitives are not tied to a scene

The primitives are the grid, tiles, sections, tabs, widgets, filters and the time range picker.
The `/dashboard-v2` scene is one host that composes them. It is not where they belong.

- A host picks which primitives it uses and how. It can render a full dashboard, one tile, or a filter bar over its own content.
- Components know nothing about the scene around them. They get data and callbacks through props, a `DashboardController`, or a small context such as `FiltersContext`. They never read a scene logic, the URL, feature flags or the current team.
- The host owns everything scene-specific: where the document comes from and how it is saved, who can edit it, which widget types and filter kinds exist, and how queries run. `scene/` holds that code for the `/dashboard-v2` scene, and no primitive imports from it.
- A primitive renders with only the providers it needs. Do not add a provider that every primitive must have before it can render.

### A dashboard in another product

Pass your own state to `DashboardView` as props. Pick the widget types and the query runner your product needs.
`scene/DashboardScene.tsx` is the full example.

```tsx
const { filters, timeRange } = useDashboardFilters({ types: myFilterTypes, time: { timezone } })
return (
  <DashboardView
    dashboard={dashboard}
    activeTabId={activeTabId}
    widgets={MY_WIDGETS}
    disabledReasonFor={disabledReasonFor}
    onEdit={onEdit}
    onActiveTabChange={setActiveTab}
    filters={filters}
    timeRange={timeRange}
    header={<MyHeader />}
  />
)
```

Event handlers, `history` and `refresh` can be written inline. Keep `dashboard`, `widgets`, `filters`, `timeRange`, `disabledReasonFor`, `tileActions` and `dashboardActions` the same between renders, such as from a logic, a hook or a module constant. A new one re-renders every tile.

Leave out what you do not need. With no `filters`, `timeRange`, `refresh` or `history`, the dashboard shows no filter bar, picker, refresh button or undo.

### One tile on its own

Render `WidgetCard` with the widget and the widget types that can draw it. No dashboard, grid or controller is needed.
Wrap it in `FiltersContext` or `RefreshContext` only when the page has filters or a refresh to pass down.

```tsx
<FiltersContext.Provider value={{ time: { from: 'now-30d', to: 'now' }, filters: [] }}>
  <WidgetCard widget={signupsChart} widgets={[createChartWidget({ runQuery: myRunner })]} />
</FiltersContext.Provider>
```

## Tiles and widgets

- A tile is the container. It owns what every tile shares: where it sits in the grid, dragging and resizing, the right-click menu, and its parts and appearance. Tile code lives in `frontend/tiles/`.
- A widget is the content a tile shows, such as a chart or markdown. A team adds its own widget type through a `WidgetDefinition` and passes it to the dashboard. Widget code lives in `frontend/widgets/`.
- A tile does not know which widget it holds. Behavior that only one kind of content needs goes in that widget type, not in the tile.
