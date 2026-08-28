# ProductEmptyState

The empty state a product scene shows until it has received real data: the product pitch and install command on the left, an animated preview of the product filled with example data on the right. Users can skip it (stored locally in the browser) unless the product sets `skippable: false` (creation-first products whose gated scene is just an empty list), and it disappears on its own once data arrives — gating is driven by real data detection, never by dismissal flags.

Scenes opt in declaratively: set `emptyState` on the scene's `SceneExport` and the app shell handles loading, empty, and has-data states — no branching inside the scene component.

`productSetupStatusLogic` (keyed by `ProductKey`) is the app-wide single read point for "is product X set up?"; each product's detection logic pushes its status into it.

Most detection logics are one call to `createSetupDetectionLogic` (`setupDetectionLogic.ts`): the product supplies a `detect` function resolving its status, and the factory owns the shared contract — detect on mount, optionally poll until data lands (stopping for good on `has-data`), and fail open on errors so a broken query never strands the gate on its spinner. Products whose detection drives more than the gate (extra selectors, staged dashboards like MCP analytics) keep a bespoke logic that pushes into `productSetupStatusLogic` directly.

Products detectable from event definitions also declare a `setupProbe` in their manifest, which `productSetupPreloadLogic` answers at app boot with one batched request — so the status is usually known before the scene is ever opened. Probes support a `staleAfterDays` window for products where old, abandoned data shouldn't count as set up.

**To adopt this for your product, follow the `building-product-empty-states` skill** (`.agents/skills/building-product-empty-states/SKILL.md`). Reference adoption: `products/mcp_analytics/frontend/emptyState/`.

`ProductIntroduction` is deprecated in favor of this component.
