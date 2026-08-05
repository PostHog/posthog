---
name: building-product-empty-states
description: Guide for adding a product setup empty state — the skippable first-run screen a product scene shows until real data arrives, built on the shared ProductEmptyState component. Use when adding an empty state or first-run/setup screen to a product scene, declaring `emptyState` on a `SceneExport`, writing a product setup-status detection logic, building an animated example-data preview widget, or migrating away from the deprecated `ProductIntroduction` component. Covers the `productSetupStatusLogic` single-layer contract, real-data detection rules, local-only skip semantics, wizard commands, and design tokens.
---

# Building product empty states

Before a user has set a product up, its scene should show a setup empty state: the product pitch and install command on the left, an animated preview of the product filled with realistic example data on the right. The shared component lives in `frontend/src/lib/components/ProductEmptyState/`; MCP analytics (`products/mcp_analytics/frontend/emptyState/`) is the reference adoption.

`ProductIntroduction` is **deprecated** — don't add new call sites. Both of its jobs fold into this system: "product not installed" (data-existence detection) and "no entities yet" (entity-count detection with a `primaryAction` create CTA).

## How it works

1. A scene declares `emptyState` on its `SceneExport`. The app shell (`frontend/src/scenes/App.tsx`) wraps the scene in `ProductEmptyStateGate` — the scene component itself contains **no** empty-state branching.
2. The gate mounts the product's **detection logic**, which pushes a normalized status into `productSetupStatusLogic({ productKey })` — the app-wide single read point for "is product X set up?".
3. The gate renders the setup empty state for `needs-setup` / `waiting-for-data`, and the scene untouched for `has-data`. While `loading` it shows the standard scene-level spinner — the one shared loading treatment. **Never add a product-specific loading fallback.**
4. Statuses are **preloaded at app boot**: `productSetupPreloadLogic` (mounted in `App.tsx`) answers every manifest-declared probe (each product's `setupProbe`, aggregated into `productSetupProbes`) with one combined event-count query on idle, so by the time a user opens the scene the status is usually already known and the spinner never shows. The product's in-scene detection stays the fresher source of truth.
5. Users can always **skip**. Skip is local-only (localStorage, keyed team + product, never backend-persisted); detection keeps polling, and a slim "Set up" banner stays visible until data lands.

## Adoption steps

### 1. Write (or extend) the detection logic

The status must come from a **real signal**: a data-existence query (HogQL count / exists API), the product's opt-in flag, or an entity count for creation-first products. Never a dismissal flag — `has_completed_onboarding_for` is routing metadata, not evidence of data.

Template: `products/mcp_analytics/frontend/mcpAnalyticsOnboardingLogic.ts` — a cheap event-count loader with `refresh: 'force_blocking'` (a cached pre-ingestion `[0,0]` would otherwise stick), a `cache.disposables` poll that stops once data arrives, and product-intent registration. Push the status from a listener:

```ts
connect(() => ({
    actions: [productSetupStatusLogic({ productKey: ProductKey.MY_PRODUCT }), ['setDetectedStatus']],
    values: [productSetupStatusLogic({ productKey: ProductKey.MY_PRODUCT }), ['status as setupStatus']],
})),
listeners(({ actions, values }) => ({
    loadSignalsSuccess: () => actions.setDetectedStatus(values.hasData ? 'has-data' : 'needs-setup'),
    loadSignalsFailure: () => {
        // Never strand the gate on its spinner: if nothing has answered yet, fail
        // open to the real scene. Don't downgrade an existing answer on a poll blip.
        if (values.setupStatus === 'loading') {
            actions.setDetectedStatus('unknown')
        }
    },
})),
```

Statuses: `loading` (not yet known - the gate holds a spinner, never flashes the empty dashboard), `unknown` (detection failed with no earlier answer - the gate fails open to the scene), `needs-setup`, `waiting-for-data` (optional middle state: instrumented but no traffic yet), `has-data`. Binary products simply never emit `waiting-for-data`. **Your detection logic must handle its failure path** - a query that fails forever must not leave the status `loading`. Statuses are stamped with the team they were detected for, so project switches automatically reset to `loading`.

### 2. Create the config

`products/<product>/frontend/emptyState/<product>EmptyState.tsx` exports a `SceneProductEmptyState` (see `lib/components/ProductEmptyState/types.ts` for every field). Reference: `products/mcp_analytics/frontend/emptyState/mcpAnalyticsEmptyState.tsx`. Notes:

- **Accent**: use the product's `--color-product-<name>-light`/`-dark` token (`frontend/src/styles/base.scss`). If your product has none, add one there (get the color from design) rather than hardcoding a hex.
- **Wizard vs primary action**: SDK-installed products set `wizard: { slug }` (the slug must exist in `@posthog/wizard`); creation-first products (flags, surveys) set `primaryAction` instead. Self-hosted degrades automatically: no cloud → the terminal hides and the manual path is promoted.
- **`featureFlag`**: set it when the scene is already flag-gated (so the scene's own gate keeps handling flag-off) or to roll the empty state out gradually.
- **Hedgehog**: a `pngHoggie(...)`-wrapped module — import only inside the product chunk (eager-graph guard: `frontend/bin/check-eager-graph.mjs`). Never hardcode image URLs (e.g. Cloudinary) — `@posthog/brand` assets only.
- **`text` is keyed by mode**: provide the `needs-setup` base; add a `waiting-for-data` entry only if your product has that middle state (missing fields fall back to the base). Sentence case, benefit-first, no AI tells (see "User-facing copy" in `CLAUDE.md`).
- **Product header**: the gate keeps the product header (name, description, icon) above the empty state automatically, sourced from the scene's `SceneConfig` in your product manifest — make sure your manifest's scene entry has `name`, `description`, and `iconType` set.

### 3. Build the signature preview

`Preview` is the right-hand widget: the product's most recognizable UI, populated with **static, realistic fake data** (label it "example data"). Reference: `products/mcp_analytics/frontend/emptyState/MCPToolCallPreview.tsx`.

- The shared layout renders it vertically centered on a darker full-height panel — the preview itself must **never scroll or loop**; a handful of static rows is the whole job. Style with tailwind; any motion is CSS only (no `setInterval`, no computed timestamps) with `motion-reduce:` variants for reduced motion.
- Honor the `mode` prop: `waiting-for-data` should read as "listening" (e.g. a pinned spinner row).

### 4. Declare it on the scene

```ts
export const scene: SceneExport = {
  component: MyScene,
  logic: mySceneLogic,
  productKey: ProductKey.MY_PRODUCT,
  emptyState: myProductEmptyState,
}
```

Then **delete** the scene's bespoke empty/loading branches (including any custom loading component) — the gate owns them now. This is strictly an **in-product** surface: do not modify the app-wide onboarding flow (`frontend/src/scenes/onboarding/`), and if the product currently redirects never-set-up users into that flow, remove the redirect — the empty state now covers first-visit setup right in the scene (reference: `mcpAnalyticsSceneLogic.ts`, which kept only its landing-tab logic).

### 4b. Register a boot-time probe

Declare a `setupProbe` in your product manifest (`products/<name>/manifest.tsx`) - the `productKey`, the event names that prove your product has data (and optionally the "instrumented but no traffic" events), and the `featureFlag` to gate on, mirroring your detection logic's semantics. `build-products.mjs` aggregates every manifest's `setupProbe` into `productSetupProbes` (regenerate with `pnpm build:products`), and `productSetupPreloadLogic` answers them at boot. This is what lets the app resolve your status before the user ever opens the scene. The probe query only looks back `PRELOAD_LOOKBACK_DAYS` (so it prunes to recent partitions); your in-scene detection stays the source of truth for anything older. The `ProductSetupProbe` shape and the count-to-status mapping live in `lib/components/ProductEmptyState/setupProbes.ts`. Products whose detection isn't event-based (exists APIs, entity counts) skip this for now; their status resolves on first scene visit.

### 5. Test the status mapping

Extend the detection logic's existing jest file with a parameterized push-through case: mount with mocked signals, assert `productSetupStatusLogic({ productKey }).values.status`. Reference: `products/mcp_analytics/frontend/mcpAnalyticsOnboardingLogic.test.ts`. Run `/writing-tests` first; don't re-test the shared gate or skip mechanics (covered in `productSetupStatusLogic.test.ts`).

### 6. Add storybook coverage

Add one story per mode to `lib/components/ProductEmptyState/ProductEmptyState.stories.tsx` with `productEmptyStateStory(myProductEmptyState, mode)` (from `storybookHelpers.ts`) - it renders your real config and gives you visual-regression snapshots for free. Default mocks answer queries and product intents so a bare call renders cleanly; pass `mocks` to drive your status indicator into a specific state (see the MCP stories).

## Migrating a ProductIntroduction call site

- Full-scene "product not set up" uses → this system, via steps 1-4.
- Entity-list empties ("create your first X") → detection = entity count, `primaryAction` = the create button.
- The SetupPrompt family (error_tracking, logs, tracing, metrics, ai_observability) already has detection logics — step 1 is just the `connect` + push; then replace the wrapper with a scene-level `emptyState` declaration.
- `has_seen_product_intro_for` dismissals are superseded by local skip; don't migrate the flag.

## QA checklist

- Dark mode, reduced motion (`prefers-reduced-motion`), self-hosted (no wizard terminal).
- Loading never flashes the real scene or the empty dashboard.
- Skip → scene renders immediately, persists across reload, "Set up" banner shows, onboarding redirect suppressed.
- Non-adopting scenes unaffected (the gate is a strict no-op without `emptyState`).
- `pnpm --filter=@posthog/frontend typescript:check`, storybook snapshots stable.
