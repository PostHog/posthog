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
5. Users can **skip** by default. Skip is local-only (localStorage, keyed team + product, never backend-persisted); detection keeps polling, and a slim "Set up" banner stays visible until data lands. Creation-first products whose gated scene is just an empty list can set `skippable: false` on the config to drop the escape hatch — the primary action is the only next step anyway.

## Adoption steps

### 1. Write (or extend) the detection logic

The status must come from a **real signal**: a data-existence query (HogQL count / exists API), the product's opt-in flag, or an entity count for creation-first products. Never a dismissal flag — `has_completed_onboarding_for` is routing metadata, not evidence of data.

Default: one call to `createSetupDetectionLogic` (`lib/components/ProductEmptyState/setupDetectionLogic.ts`). Supply a `detect` function resolving the product's status; the factory owns the shared contract - detect on mount, optionally poll until data lands (stopping for good on `has-data`, pausing on hidden tabs), fail open on errors, and wait out bootstrap before the first check:

```ts
export const logsSetupLogic = createSetupDetectionLogic({
  productKey: ProductKey.LOGS,
  path: ['products', 'logs', 'frontend', 'emptyState', 'logsSetupLogic'],
  detect: async () => ((await api.logs.hasLogs()) ? 'has-data' : 'needs-setup'),
  // Only for products where data arrives from outside (SDK events); entity-count
  // products omit it - the gate remounts the logic on every scene entry.
  pollIntervalMs: 20000,
})
```

`detect` composes freely: retry inside it with `retryWithBackoff`, return `unknown` for "cannot tell" (e.g. no access), return `waiting-for-data` from an opt-in flag + count check. When the query is a fresh event count, use `refresh: 'force_blocking'` - a cached pre-ingestion `[0,0]` would otherwise stick. `recheckActionTypes` re-detects immediately when app state changes elsewhere (a team-setting opt-in). `cacheHasData` remembers a has-data answer in localStorage so returning users skip the spinner and the query - use it for products with no boot-time probe.

Products whose detection drives more than the gate (extra selectors, staged dashboards) keep a bespoke logic instead - template: `products/mcp_analytics/frontend/mcpAnalyticsOnboardingLogic.ts`. It must push the status from a listener and handle failure the same way the factory does:

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
- **Wizard vs primary action**: SDK-installed products set `wizard: { slug }` (the slug must exist in `@posthog/wizard`); creation-first products (flags, surveys) set `primaryAction` instead. Self-hosted degrades automatically: no cloud → the terminal hides and the manual path is promoted. If the create action needs hooks (e.g. it opens PostHog AI via `useMaxTool`, like user research's "New topic"), provide a `PrimaryAction` component instead of `primaryAction` - it renders in the same slot and takes precedence.
- **Permissions and selectors on the primary action**: set `primaryAction.accessControl` to the same resource type and level the gated scene's own create button uses. Without it a viewer gets an enabled button and only learns they can't create when the form fails to save. Set `primaryAction.dataAttr` to the attr that scene button carries, so an end-to-end spec keeps one selector whether it lands on the scene or the empty state. A `PrimaryAction` component wraps its own `AccessControlAction`.
- **`featureFlag`**: set it when the scene is already flag-gated (so the scene's own gate keeps handling flag-off) or to roll the empty state out gradually.
- **Hedgehog**: a `pngHoggie(...)`-wrapped module — import only inside the product chunk (eager-graph guard: `frontend/bin/check-eager-graph.mjs`). Never hardcode image URLs (e.g. Cloudinary) — `@posthog/brand` assets only.
- **`text` is keyed by mode**: provide the `needs-setup` base; add a `waiting-for-data` entry only if your product has that middle state (missing fields fall back to the base). Sentence case, benefit-first, no AI tells (see "User-facing copy" in `CLAUDE.md`).
- **Product header**: the gate keeps the product header (name, description, icon) above the empty state automatically, sourced from the scene's `SceneConfig` in your product manifest — make sure your manifest's scene entry has `name`, `description`, and `iconType` set.

### 3. Build the signature preview

`Preview` is the right-hand widget: the product's most recognizable UI, populated with **static, realistic fake data** (label it "example data"). References: `products/mcp_analytics/frontend/emptyState/MCPToolCallPreview.tsx`, `products/feature_flags/frontend/emptyState/FeatureFlagPreview.tsx`, `products/experiments/frontend/emptyState/ExperimentPreview.tsx`.

This is not a flat mock - the bar is "fun and involved", and the references set it:

- **Layer 2-3 small cards** that tell one story together (a list + the mini app it drives + a stat card with a chart), not a single panel of rows.
- **One real interaction with a visible payoff.** Drive it with a hidden checkbox/radio and `:checked ~` styles - clicking a flag row flips a mini app's UI and steps a conversion chart up at a "Released" marker; picking a variant highlights its interval and re-skins the app. No React state, no JS timers (`setInterval` is banned; CSS keyframes only).
- **Ambient motion so it feels alive at rest:** a trace segment cycling along a sparkline, a pulsing "Running" dot - subtle and continuous. Do **not** auto-toggle the interactive state on a loop - a UI that flips itself reads as broken, not alive; the user flips it, ambient motion does the rest.
- **No layout shift on state change:** stack on/off variants in one grid cell and crossfade opacity; never swap `display` or animate heights for state text.
- **Never paint text in the raw product accent.** Those tokens are sidebar icon tints; on the light surface most land under the 4.5:1 AA floor as text. Use `@include preview-accent-text(var(--<x>-preview-accent))` for every `color:` declaration and keep the raw accent for fills, borders, and strokes.
- **Crossfade with the `preview-swap-hidden` / `preview-swap-visible` mixins** (`lib/components/ProductEmptyState/_previewMixins.scss`), never bare `opacity`. Opacity alone leaves the hidden half in the accessibility tree and the tab order, so a screen reader announces both states at once and a keyboard user can land on an invisible button. The mixins add `visibility` on a delay, which keeps the fade and costs no layout shift.
- The hidden input stays keyboard-focusable, so the row it labels needs a `:focus-visible` outline (WCAG 2.4.7).
- The preview must **never scroll**; guard all animation with `prefers-reduced-motion` and an `inStorybook()`-driven static class so visual-regression snapshots stay stable.
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

Declare a `setupProbe` in your product manifest (`products/<name>/manifest.tsx`) - the `productKey`, the event names that prove your product has data (and optionally the "instrumented but no traffic" events), and the `featureFlag` to gate on, mirroring your detection logic's semantics. `build-products.mjs` aggregates every manifest's `setupProbe` into `productSetupProbes` (regenerate with `pnpm build:products`), and `productSetupPreloadLogic` answers them all at boot with one batched event-definitions request (Postgres, cheap). This is what lets the app resolve your status before the user ever opens the scene; your in-scene detection stays the fresher source of truth. Set `staleAfterDays` when your detection logic uses a staleness window, so a project that stopped sending long ago reads as needing setup at boot too. Use string literals for event names - the probe is cloned into the eager generated `products.tsx`, so it must not import from your product chunk. The `ProductSetupProbe` shape and the definitions-to-status mapping live in `lib/components/ProductEmptyState/setupProbes.ts`. Products whose detection isn't event-based (exists APIs, entity counts) skip this; their status resolves on first scene visit.

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
