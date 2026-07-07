# Toolbar bundle migration tracker

This file is the committed source of truth for the toolbar bundle modernization (single-file IIFE → classic-script loader + code-split ESM, plus import-graph untangling). Agents and humans working on it: read this first, work the steps **in order**, and in every PR update the Status block and tick the boxes you completed. Keep edits to this file inside the same PR as the work they describe.

## Status

- **Current step**: Steps 1–4 all implemented and in review as a 5-deep Graphite stack (drafts). Next: merge the base of the stack before extending further (per repo stacking guidance), then remaining Step 5/6 edges and Step 7 lazy boundaries.
- **Last updated**: 2026-07-07
- **PRs**: Step 1 — `rafa/toolbar-migration-1-graph-guard` (#69045); Step 3 — `rafa/toolbar-migration-2-products-urls-split` (#69071); chain cuts + shim-leak fix — `rafa/toolbar-migration-3-shim-leak-and-chain-cuts` (#69088); Step 2 — `rafa/toolbar-migration-4-loader-esm-splitting` (#69093); Step 4 — `rafa/toolbar-migration-5-types-replay-shared-cut` (each stacked on the previous)
- **Reorder note (resolved)**: a trial Step 2 build emitted **487 dead chunks** — with `products.tsx` reachable, every product scene's dynamic import becomes a real chunk in `dist/toolbar/`. The gate was: flip the format only once `products.tsx` leaves the graph. That's now done via two moves in the third PR. First, the remaining chains all funneled through one root cause: the kea shims only matched exact alias strings (`scenes/teamLogic`), so relative imports (`dataThemeLogic` → `./teamLogic`) and `~/`-prefixed imports pulled the REAL logics and their whole app graph — fixed with relative + `~/` matching in `createToolbarModulePlugin`, disconnecting `products.tsx`, `scenes.ts`, `teamLogic`, `PersonDisplay`, and `experimentsLogic` in one move. Second, `scenes/urls` itself (imported by lib components shared with the app) is shimmed to the toolbar's parity-tested `~/toolbar/urls` duplicate from Step 3, taking the last products-manifest path out. Bundle graph 8448 → ~1000 files (99 → ~13.5 MiB source), shipped `dist/toolbar.js` 9.95 MB → ~4 MB (was just under the 10 MB CloudFront cliff). Graph budget ratcheted 110 MB → 18 MB.
- **posthog-js prerequisite**: DONE — release pipeline is layout-agnostic and verified as a no-op against today's build. Nothing blocks any step. See Step 0 for the constraints it imposes on the build here.

## Why

The toolbar (`frontend/src/toolbar/`, entry `frontend/src/toolbar/index.tsx`) is built as a single IIFE (`frontend/toolbar-config.mjs`), which force-inlines all 157 dynamic `import()`s in its graph, and it imports the main app — `scenes/urls.ts:5` pulls `~/products` (every product manifest), `~/types` has runtime imports (`lib/Chart`, `lib/api`, an `hls.js`-dragging re-export). Tree shaking can't rescue it (no `sideEffects` fields), so `toolbar-config.mjs` keeps hand-curated denylists + kea shims (`frontend/src/toolbar/shims/`) — which leaked until the third PR (`scenes/dataThemeLogic.tsx` imports `./teamLogic` relatively, bypassing the then-exact-string shim; fixed by matching relative and `~/` imports too). Before that fix the bundle sat just under the 10MB CloudFront gzip cliff (`frontend/bin/check-toolbar-size.mjs`); it now ships at ~4.06 MB.

Measured from `frontend/toolbar-esbuild-meta.json` (dev bytes; prod ≈ dev × 0.42):

- 6.43MB of 22.17MB is reachable only via existing `import()`s → defers with zero source changes once splitting lands.
- ~50 import edges cross from toolbar/lib into the app zone; cutting ~33 of them → 8.62MB dev (−61%).
- Single edge cuts often save ~0 bytes (redundant paths); the per-step metric is the guard's shrinking allowlist, not bytes.

End state: ~1-2KB loader, enforced eager-chunk budget, every chunk far under 10MB, denylist reduced to documented seams, `check-toolbar-graph.mjs` preventing regression.

## Compatibility model (do not break this)

posthog-js (all versions, forever) injects a **classic** `<script crossOrigin="anonymous">` for `toolbar.js` and on `load` calls `window.ph_load_toolbar(params, posthog)` (fallback `ph_load_editor`). The loader must keep that contract exactly; chunk loading is internal via `import()` relative to `document.currentScript.src`. Consequences:

- Old SDKs on the default unversioned `/static/toolbar.js` get the split toolbar transparently (better: smaller eager fetch).
- Old SDK versions on the versioned CDN (`strict_script_versioning`) keep their pinned single-file builds untouched forever.
- New SDK releases publish the split layout into new pinned dirs — the posthog-js publish step is already layout-agnostic (Step 0).
- `window.posthogToolbarController` is public surface — the loader must expose a forwarding stub synchronously.
- No eval / `new Function` anywhere new (customer CSPs; `frontend/bin/check-toolbar-csp-eval.mjs`).

## Steps

Work one step per PR (Graphite stack via `gt`; keep the stack shallow — merge the base before extending; batch pushes). Every PR: run the verification commands at the bottom and update Status.

### Step 0 — posthog-js prerequisite (external repo) — DONE

- [x] Requirements doc written and handed off with the posthog-js change (originally drafted here as `POSTHOG_JS_TOOLBAR_REQUIREMENTS.md`; it now lives with the posthog-js work)
- [x] posthog-js release pipeline is layout-agnostic: `collectReleaseAssets()` (`tooling/release/src/upload-posthog-js-s3.ts`) recursively publishes `dist/toolbar/` when present, with explicit content types (`.js` → `application/javascript` — ESM chunks are strict-MIME CORS fetches) and `max-age=31536000, immutable`, at the versioned, major-alias, AND compatibility prefixes; the `build-toolbar` job in `release.yml` accepts an unhashed canonical `toolbar.js`/`toolbar.css`, greps `toolbar/` too for `TOOLBAR_PUBLIC_PATH`, strips source maps inside `toolbar/`, and uploads `frontend/dist/toolbar` (missing dir = warn). Covered by an end-to-end test (`upload-posthog-js-s3.test.ts`). Verified as a no-op against today's single-file build.

**Constraints this imposes on Step 2** (design already matches; do not drift):

- The loader must be emitted as unhashed canonical `dist/toolbar.js` (their normalize step expects it).
- Keep the `__POSTHOG_TOOLBAR_PUBLIC_PATH__` define present in the shipped app output (their verify step greps `toolbar.js` + `toolbar/` for it; it remains the runtime CSS URL mechanism).
- Chunk resolution must stay relative to `document.currentScript.src` / the importing module — never absolute — because the same artifacts are served from the versioned, major-alias, and compatibility prefixes.
- Don't rely on source maps being served next to chunks on the versioned CDN (they're stripped there).

### Step 1 — boundary guard (so later steps ratchet)

- [x] Commit this tracker
- [x] New `frontend/bin/check-toolbar-graph.mjs` reading `frontend/toolbar-esbuild-meta.json`. It computes the "survivor" closure (reachable from `src/toolbar/index.tsx` without walking into the app zone: `src/products*`, `src/scenes/**`, `src/layout/**`, `src/models/**`, `products/**`) and fails on (a) any survivor → app-zone edge not in the checked-in baseline `frontend/bin/toolbar-graph-baseline.json` (47 edges on 2026-07-07), (b) baseline entries that no longer exist (delete them to ratchet), (c) denied packages (`monaco-editor`, `chart.js`, `mermaid`, `hls.js`) present anywhere in the graph, (d) total source input bytes over budget (99.74 MiB measured, 104.9 MiB budget)
- [x] oxlint: `frontend/src/toolbar/**` override in `.oxlintrc.json` with `no-restricted-imports` (scenes/products/layout/models patterns with today's imports as explicit `!` exceptions; `lib/api` value imports). Lint is fast feedback; the metafile check is the source of truth
- [x] Wire into `.github/workflows/ci-frontend.yml` next to `check-toolbar-size` (runs against the PR's own metafile, before the base rebuild overwrites it)

Done when: CI runs the graph check green with the baseline allowlist.

### Step 2 — loader + ESM code splitting (in review: `rafa/toolbar-migration-4-loader-esm-splitting`)

Landed layout: `dist/toolbar.js` (1.2KB classic loader) + `dist/toolbar/` (ESM entry `toolbar-app-<hash>.js`, hashless fallback `toolbar-app.js`, `chunk-*-<hash>.js`, per-chunk CSS, `toolbar-app.css` hashless entry CSS loaded into the shadow root, `assets/` fonts) + `dist/toolbar.css` (transition-window copy for stale-cached single-file toolbar.js only).

- [x] `frontend/toolbar-config.mjs`: `getToolbarAppBuildConfig` (ESM, `splitting: true`, outdir `dist/toolbar`, per-file `var define = undefined;` banner) + `finalizeToolbarBuild` (hashless copies, CSS promotion, loader build with `__POSTHOG_TOOLBAR_APP_ENTRY__` baked in), wired into `frontend/build.mjs` and `frontend/bin/build-toolbar.mjs` (dev watch mode verified)
- [x] **`publicPath` must stay unset on the app build** (explicit `publicPath: undefined` to override commonConfig's `/static`): esbuild bakes publicPath into chunk import specifiers as absolute URLs, which breaks serving the same artifacts from any region/self-hosted/CDN prefix. Chunk imports are relative; svgs inline as data URLs (a relative specifier string would resolve against the customer page URL); font url()s in the CSS are relative and resolve because the CSS is fetched from inside `dist/toolbar/` (`ToolbarApp.tsx` now loads `toolbar/toolbar-app.css`). Bonus: retires the hardcoded `us.posthog.com` asset URLs (EU used to load fonts from US)
- [x] `frontend/src/toolbar/loader.ts`: classic-script contract kept (`ph_load_toolbar`/`ph_load_editor`/controller stub synchronously); import with retry/backoff; hashless `toolbar-app.js?t={5-min bucket}` fallback; degrade to no-toolbar with console.warn
- [x] `frontend/src/toolbar/index.tsx`: `export loadToolbar` + controller; window assigns kept for back-compat
- [x] `check-toolbar-size.mjs` rewrite: per-file 10MB CloudFront limit across all outputs, eager-set budget 3.3MB (measured 2.97MB), loader <20KB (measured 1,153 bytes). Shared metafile helpers in `bin/toolbar-metafile.mjs`
- [x] `check-toolbar-csp-eval.mjs` rewrite: scoped counts — loader 0, eager closure 1 (toolbarLogic probe), total 5 (4 pixi in lazy hedgehog chunks)
- [x] Per-chunk CSS accepted (esbuild 0.25 emits it): only the entry CSS is loaded into the shadow root, so toolbar features must keep styles statically imported — verified all chunk-CSS inputs also land in the entry CSS; recheck at Step 7
- [x] `buildInParallel` now logs callback errors before exiting (previously swallowed silently)
- [x] Playwright smoke test (throwaway, not committed): static server over dist/ + strict CSP (`script-src 'self'`, no unsafe-eval) + classic-script injection exactly like posthog-js + `ph_load_toolbar` call → entry + 6 eager chunks fetched relative to the loader origin, shadow root mounts, controller stub delegates (`isLoaded` flips true), zero page errors
- [x] Real-SDK smoke test (throwaway): published posthog-js (1.398.2 from node_modules, untouched) drives the whole flow — parses `#__posthog` authorize state, injects `/static/toolbar.js?v=&t=`, loader import()s the split app, shadow root mounts, controller live, zero page errors
- [x] Local-stack click-through (Playwright driving `hogli up` at localhost:8010, throwaway script): real workspace via `/api/setup_test/`, authorized URL added, `redirect_to_site` → host page → toolbar mounts unauthenticated → full OAuth authorize flow (Authenticate → confirm modal → OAuth grant → redirect back) → `isAuthenticated: true` → all six feature menus open with real seeded data (heatmaps, actions, flags, event debugger, web vitals, experiments) → clicking Hedgehog mode fetches 10 pixi/hedgehog chunks on demand → styled bar renders from shadow-root CSS. Note: `redirect_to_site` no longer issues a `temporaryToken` — toolbar auth is OAuth now, so the unauthenticated first mount is expected behavior, not a regression
- [ ] `Toolbar.stories.tsx` green in CI (runs on the PR)

Result: 1.06MB (26%) of app JS deferred with zero source changes; every file far under the 10MB cliff (largest 1.77MB). Known-unsupported: exact-path CSP allowlists (`script-src .../toolbar.js`) — chunks need the directory allowed.

### Step 3 — toolbar-owned `urls` duplicate (landed before Step 2, see reorder note)

Approach (revised on review): rather than restructuring the generated products manifest so `scenes/urls` stops dragging it in, the toolbar gets its own deliberately duplicated `frontend/src/toolbar/urls.ts` with only the url helpers it links to, and a parity test keeps it honest. A first version of this PR split `products-urls.tsx` out of the generator; that was reverted as over-engineered — the duplicate + test is simpler to review and keeps the generator untouched.

- [x] `frontend/src/toolbar/urls.ts`: the 12 helpers toolbar code uses (`action(s)`, `experiment(s)`, `featureFlag(s)`, `productTour`, `sessionProfile`, `settings`, `survey(s)`, `webAnalyticsWebVitals`), plus a documented `urlToResource` null stub (the real one walks a matcher tree built from every product manifest; its only toolbar-shipped consumer is Link's drag-to-notebook annotation, inert on customer pages)
- [x] `frontend/src/toolbar/urls.test.ts`: parity test asserting each helper matches `scenes/urls` byte-for-byte over sample args (the test deliberately crosses the boundary — that's its job); a helper without samples fails
- [x] All 11 toolbar files import `~/toolbar/urls`; their `-> src/scenes/urls.ts` baseline edges are deleted (47 → 36)
- [x] The 3 lib files shipped in the toolbar (`TZLabel`, `HeatmapEventsPanel`, `Link`) still import `scenes/urls` — they're shared with the app and can't be repointed; the third PR's `scenes/urls` shim resolves them to the toolbar duplicate at build time, removing their edges and taking `scenes/urls` + the products manifest out of the toolbar graph entirely
- [ ] Verify the app/exporter eager-graph improvements with the `check-eager-graph` owners

### Step 4 — `~/types` hygiene (in review: `rafa/toolbar-migration-5-types-replay-shared-cut`)

**Finding that shrank this step**: esbuild already erases imports whose specifiers are all type-position-only (they show as `external: true` in the metafile with no resolved edge), so the planned `import type` conversion and leaf-enum extraction were unnecessary for the bundle graph — `src/types.ts` had exactly ONE surviving runtime import: the `SnapshotSourceType` value re-export.

- [x] `export { SnapshotSourceType }` → `export type { ... }` in `types.ts`; the three value-users (snapshotDataLogic + two player tests) import the enum from `@posthog/replay-shared` directly. Removes all 27 replay-shared files from the toolbar graph
- [x] Retired the `hls.js` deny in `toolbar-config.mjs` (its only path in was replay-shared); reintroduction still fails via FORBIDDEN_PACKAGES in `check-toolbar-graph.mjs`
- [x] Ratchets: graph budget 18 MB → 15.5 MB (measured 13.40 MiB, 1010 files), eager budget 3.3 MB → 3.05 MB (measured 2,764,847 — the cut freed 203 KB of eager JS and one eager chunk)
- [-] `import type` conversion / `lib/Chart` type-only / leaf-enum moves: NOT NEEDED for the bundle (see finding); only worth doing as general hygiene if oxlint `consistent-type-imports` lands repo-wide
- [ ] `chart.js` deny retirement: still blocked — `lib/Chart` stays denied because Sparkline/LineGraph value-import it outside types.ts (Step 6 territory)

### Step 5 — toolbar-owned direct edges

- [x] `toolbar/experiments/experimentsTabLogic.tsx`: stopped importing `scenes/experiments/experimentsLogic` — the pure status helpers (`getExperimentStatus`/`isLaunched`/`isExperimentPaused`/`hasEnded`) moved to leaf module `scenes/experiments/experimentStatus.ts` (re-exported from experimentsLogic for app importers); data fetching already went via `toolbarApi`
- [ ] `toolbar/debug/EventDebugMenu.tsx`: move `PanelSettings` from `scenes/session-recordings/components/` to `lib/components/`
- [ ] `toolbar/debug/eventDebugMenuLogic.ts`: drop/trim the 339KB `core-filter-definitions-by-group.json` taxonomy import
- [ ] `toolbar/actions/StepField.tsx`: move `products/actions/frontend/utils/hints` to `lib/` (or allowlist — it's ~0KB)

### Step 6 — shared lib → scenes back-edges (each also helps the main app)

- [ ] `lib/lemon-ui/Link/Link.tsx` → `DraggableToNotebook` (drags notebooks → tiptap): invert with a registry/context seam (the flagship shim→DI replacement)
- [ ] `lib/lemon-ui/LemonColor/*` → `scenes/dataThemeLogic` (its `./teamLogic` import is now shimmed, so this edge is boundary-only, not a leak): theme via props/context
- [ ] `lib/lemon-ui/LemonMarkdown/index.ts`: stop re-exporting `LemonMarkdownWithMermaid` from the barrel (retires the `mermaid` deny for both bundles)
- [x] `HeatmapEventsPanel` → `PersonDisplay`: replaced with a plain span (PersonDisplay renders exactly that for a distinct_id-only person with `noPopover`); `TZLabel` → teamLogic edge now shimmed at resolve time (`~/scenes/teamLogic` matching)
- [ ] `TZLabel` → urls; `eventUsageLogic` → preflight/web-analytics edges; move `KeyboardShortcut` out of `layout/navigation-3000` into `lib/`

### Step 7 — lazy boundaries in toolbar source

- [ ] Convert the nine `visibleMenu` bodies in `frontend/src/toolbar/bar/Toolbar.tsx` + `SurveySidebar`/`ProductToursSidebar`/modals to `React.lazy(() => retryImport(() => import(...)))` with `Spinner` fallback. Largest first: actions/TaxonomicFilter, experiments, surveys, heatmaps, web-vitals, debugger (react-json-view), product tours
- [ ] Audit eagerly-mounted per-tab logics (e.g. `webVitalsToolbarLogic.mount()` in `ToolbarApp.tsx`) — keep a slim eager core where background collection is deliberate
- [ ] Ratchet the eager budget down

### Step 8 — tree-shaking enablers + cleanup (highest breakage risk; last)

- [ ] Add `"sideEffects"` to `frontend/package.json` + lemon-ui package: `**/*.scss`, `**/*.css`, entrypoints, `src/toolbar/patch.ts`, kea plugin/registration modules (`src/kea-disposables.ts`), anything touching `window` at import. NOTE: the `@posthog/lemon-ui` barrel imports `global.scss` on line 1 — must be listed or styles vanish. Verify with storybook/e2e
- [ ] Ratchet budgets to the new floor; drop remaining redundant `deniedThirdPartyPackages` entries one at a time; rewrite the `toolbar-config.mjs` comment (rationale is now the eager-chunk budget, not the 10MB cliff); delete shims replaced by DI seams, document the rest as intentional injection points

### Flagged — needs product decision (not blocking)

`toolbar/product-tours/productToursLogic.ts` → `scenes/product-tours/editor/generateStepHtml.ts` is a legitimate dep costing ~1MB dev (tiptap + prosemirror + highlight.js). Right fix: precompute step HTML at authoring time in the app, store on the `ProductTourStep` payload, render sanitized in the toolbar (dompurify already bundled). Until decided, Step 7's lazy boundary defers it.

## Verification (every step)

```bash
pnpm --filter=@posthog/frontend build:esbuild
node frontend/bin/check-toolbar-size.mjs
node frontend/bin/check-toolbar-graph.mjs      # from Step 1 on
node frontend/bin/check-toolbar-csp-eval.mjs
pnpm --filter=@posthog/frontend visualize-toolbar-bundle   # eyeball the graph
```

Byte estimates in this doc are dev bytes × ~0.42 ≈ prod — verify with the real minified build. When bytes don't move, the shrinking Step 1 allowlist is the progress metric. Toolbar behavior: launch on the local app (`hogli start`) and click through the tabs; for format changes also run the CSP/old-SDK Playwright checks from Step 2.
