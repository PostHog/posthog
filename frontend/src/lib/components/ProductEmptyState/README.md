# ProductEmptyState

The empty state a product scene shows until it has received real data: the product pitch and install command on the left, an animated preview of the product filled with example data on the right. Users can always skip it (stored locally in the browser), and it disappears on its own once data arrives — gating is driven by real data detection, never by dismissal flags.

Scenes opt in declaratively: set `emptyState` on the scene's `SceneExport` and the app shell handles loading, empty, and has-data states — no branching inside the scene component.

`productSetupStatusLogic` (keyed by `ProductKey`) is the app-wide single read point for "is product X set up?"; each product's detection logic pushes its status into it.

**To adopt this for your product, follow the `building-product-empty-states` skill** (`.agents/skills/building-product-empty-states/SKILL.md`). Reference adoption: `products/mcp_analytics/frontend/emptyState/`.

`ProductIntroduction` is deprecated in favor of this component.
