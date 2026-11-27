# Primitives

Read this before you write or review any file under `frontend/`.

A team picks only the primitives it wants and composes them anywhere, the way it uses Quill components.
A design is right when any product can take one primitive and use it without the others.

## A dashboard is a JSON document

On the client, a dashboard is one `Dashboard` document (`dashboard/document/dashboardSchema.ts`), and the primitives render whatever document they get.
The document can come from a saved board, a product's own code, a fixture, or a URL. It may never be saved at all.

- A primitive renders from the document and its props alone. It never loads or saves a document, and never needs a board id to render.
- `dashboardFromJson(json, panels)` turns a document into what `DashboardView` renders, with the problems `validateDashboard` finds. A panel that fails its own type's check still loads, and its tile says why.
- An edit gives a new document through `applyEdit`. The host decides whether to keep it, save it, or drop it.
- Saving belongs to the host. `dashboard/saved/savedDashboardLogic.ts` is one way to save a document as a board, not a requirement.
- Behavior that a document cannot describe, such as a refresh interval or a person's closed sections, stays out of the document.

## Primitives are not tied to a scene

The primitives are the grid, tiles, sections, tabs, panels, filters and the time range picker.
The `/dashboard-v2` scene is one host that composes them. It is not where they belong.

- A host picks which primitives it uses and how. It can render a full dashboard, one tile, or a filter bar over its own content.
- Components know nothing about the scene around them. They get data and callbacks through props, a `DashboardController`, or a small context such as `FiltersContext`. They never read a scene logic, the URL, feature flags or the current team.
- The host owns everything scene-specific: where the document comes from and how it is saved, who can edit it, which panel types and filter kinds exist, and how queries run. `scene/` holds that code for the `/dashboard-v2` scene, and no primitive imports from it.
- A primitive renders with only the providers it needs. Do not add a provider that every primitive must have before it can render.

To compose the primitives on another product's page, follow [composing.md](composing.md).

## Tiles and panels

- A tile is the container. It owns what every tile shares: where it sits in the grid, dragging and resizing, the right-click menu, and its parts and appearance. Tile code lives in `frontend/tiles/`.
- A panel is the content a tile shows, such as a chart or markdown. A team adds its own panel type through a `PanelDefinition` and passes it to the dashboard. Panel code lives in `frontend/panels/`. To add or change a panel type, use the `/adding-dashboard-v2-panel-types` skill.
- A tile does not know which panel it holds. Behavior that only one kind of content needs goes in that panel type, not in the tile.
