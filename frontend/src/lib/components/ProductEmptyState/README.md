# ProductEmptyState

The empty state a product scene shows until it has received real data: the product pitch and install command on the left, an animated preview of the product filled with example data on the right. Users can skip it (stored locally in the browser) unless the product sets `skippable: false` (creation-first products whose gated scene is just an empty list), and it disappears on its own once data arrives — gating is driven by real data detection, never by dismissal flags.

Scenes opt in declaratively: set `emptyState` on the scene's `SceneExport` and the app shell handles loading, empty, and has-data states — no branching inside the scene component.

`productSetupStatusLogic` (keyed by `ProductKey`) is the app-wide single read point for "is product X set up?"; each product's detection logic pushes its status into it.

Most detection logics are one call to `createSetupDetectionLogic` (`setupDetectionLogic.ts`): the product supplies a `detect` function resolving its status, and the factory owns the shared contract — detect on mount, optionally poll until data lands (stopping for good on `has-data`), and fail open on errors so a broken query never strands the gate on its spinner. Products whose detection drives more than the gate (extra selectors, staged dashboards like MCP analytics) keep a bespoke logic that pushes into `productSetupStatusLogic` directly.

Products detectable from event definitions also declare a `setupProbe` in their manifest, which `productSetupPreloadLogic` answers at app boot with one batched request — so the status is usually known before the scene is ever opened. Probes support a `staleAfterDays` window for products where old, abandoned data shouldn't count as set up.

To review an empty state on a project that already has data, add `?empty_state=1` to the scene URL. It forces the `needs-setup` screen past detection and past a local skip, `?empty_state=waiting-for-data` forces the other mode, and dropping the param gives the real scene back. Use it for design review and screenshots instead of clearing a project.

**To adopt this for your product, follow the `building-product-empty-states` skill** (`.agents/skills/building-product-empty-states/SKILL.md`). Reference adoption: `products/mcp_analytics/frontend/emptyState/`.

## ProductEmptyState or ProductIntroduction?

Two components cover empty surfaces, and they are not interchangeable.

- **`ProductEmptyState`** (this component) is the first-run screen for a product landing scene: the whole scene is replaced until detection says the product has data. Use it when the surface is a product's list or overview page, reached from the navigation, and "nothing here yet" means "the product is not set up yet". It is declared on the `SceneExport`, never rendered by hand.
- **`ProductIntroduction`** (`frontend/src/lib/components/ProductIntroduction/`) is an inline panel for a surface that cannot be gated: a tab or sub-list inside an adopted product (workflow channels, message templates), a dashboard widget tile or notebook node, a section of a settings page, an activity log, or a state that is not about setup at all (no ingestion warnings, the empty Max chat history). It renders where the list would be, so the rest of the surface stays usable around it.

If a whole scene is empty because the product is not set up, adopt `ProductEmptyState`. If one part of an otherwise working surface is empty, use `ProductIntroduction`. Do not stack both on one scene: an adopted scene that still renders a `ProductIntroduction` for the same emptiness shows two setup surfaces.

To find remaining `ProductIntroduction` call sites: `git grep -ln 'ProductIntroduction' -- 'frontend/src' 'products/'`.
