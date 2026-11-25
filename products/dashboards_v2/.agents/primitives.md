# Primitives

Read this before you write or review any file under `frontend/`.

A team picks only the primitives it wants and composes them anywhere, the way it uses Quill components.
A design is right when any product can take one primitive and use it without the others.

## Tiles and widgets

- A tile is the container. It owns what every tile shares: where it sits in the grid, dragging and resizing, the right-click menu, and its parts and appearance. Tile code lives in `frontend/tiles/`.
- A widget is the content a tile shows, such as a chart or markdown. A team adds its own widget type through a `WidgetDefinition` and passes it to the dashboard. Widget code lives in `frontend/widgets/`.
- A tile does not know which widget it holds. Behavior that only one kind of content needs goes in that widget type, not in the tile.
