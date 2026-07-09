# Toolbar bundle migration tracker

This file is the committed source of truth for the toolbar bundle modernization (single-file IIFE → classic-script loader + code-split ESM, plus import-graph untangling). Agents and humans working on it: read this first, work the steps **in order**, and in every PR update the Status block and tick the boxes you completed. Keep edits to this file inside the same PR as the work they describe.

## Status

- **Current step**: Step 2 is UNBLOCKED — `src/products.tsx` (and the whole app scene graph) is out of the toolbar bundle graph as of the shim-leak fix below. Next: unstash `toolbar-step2-loader-esm-wip` (expect conflicts in `toolbar-config.mjs` — the working tree's `createToolbarModulePlugin` gained relative/`~/` shim matching that MUST be preserved) and apply the known adjustments in the Step 2 section.
- **Last updated**: 2026-07-07
- **PRs**: Step 1 — `rafa/toolbar-migration-1-graph-guard` (#69045); Step 3 — `rafa/toolbar-migration-2-products-urls-split` (#69071, stacked on Step 1); chain cuts + shim-leak fix — `rafa/toolbar-migration-3-shim-leak-and-chain-cuts` (stacked on #69071)
- **Reorder note (resolved)**: a trial Step 2 build emitted **487 dead chunks** — with `products.tsx` reachable, every product scene's dynamic import becomes a real chunk in `dist/toolbar/`. The gate was: flip the format only once `products.tsx` leaves the graph. That's now done via two moves in this PR. First, the remaining chains all funneled through one root cause: the kea shims only matched exact alias strings (`scenes/teamLogic`), so relative imports (`dataThemeLogic` → `./teamLogic`) and `~/`-prefixed imports pulled the REAL logics and their whole app graph — fixed with relative + `~/` matching in `createToolbarModulePlugin`, disconnecting `products.tsx`, `scenes.ts`, `teamLogic`, `PersonDisplay`, and `experimentsLogic` in one move. Second, `scenes/urls` itself (imported by lib components shared with the app) is shimmed to the toolbar's parity-tested `~/toolbar/urls` duplicate from Step 3, taking the last products-manifest path out. Bundle graph 8448 → ~1000 files (99 → ~13.5 MiB source), shipped `dist/toolbar.js` 9.95 MB → ~4 MB (was just under the 10 MB CloudFront cliff). Graph budget ratcheted 110 MB → 18 MB.
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

### Step 2 — loader + ESM code splitting (GATED: land after `src/products.tsx` leaves the toolbar graph, see reorder note in Status)

Implementation is done and stashed as `toolbar-step2-loader-esm-wip` (loader.ts, two-config build, esbuilder `esbuildBuild` re-export, globals.d.ts). Known adjustments still needed when unstashing: esbuild 0.25 DOES emit per-chunk CSS files — drop the single-CSS assertion in `finalizeToolbarBuild` and instead require the entry CSS (it holds all statically-reachable styles; chunk CSS is dead weight for lazy scenes, but toolbar features must keep their styles statically imported — recheck at Step 7); surface `finalizeToolbarBuild` errors (buildInParallel's catch swallows them silently).

Target layout: `dist/toolbar.js` (~1-2KB classic loader) + `dist/toolbar.css` (single file, esbuild doesn't split CSS) + `dist/toolbar/toolbar-app-<hash>.js` + `dist/toolbar/toolbar-app.js` (hashless fallback) + `dist/toolbar/chunk-*-<hash>.js`.

- [ ] `frontend/toolbar-config.mjs` returns two configs, built sequentially in `frontend/build.mjs` + `frontend/bin/build-toolbar.mjs`:
  - Toolbar App: `entryPoints: { 'toolbar-app': 'src/toolbar/index.tsx' }`, `format: 'esm'`, `splitting: true`, `outdir: dist/toolbar`, `chunkNames: 'chunk-[name]-[hash]'`, `banner: { js: 'var define = undefined;' }` (applies per output file — AMD guard on every chunk), keep `__POSTHOG_TOOLBAR_PUBLIC_PATH__` define + `createToolbarModulePlugin`, `writeMetaFile: true`. Post-build: `createHashlessEntrypoints` for `toolbar-app.js`; copy entry CSS to `dist/toolbar.css`
  - Toolbar loader: `format: 'iife'`, `outfile: dist/toolbar.js`, define `__POSTHOG_TOOLBAR_APP_ENTRY__` = hashed entry basename from the app build's metafile. Verify esbuild leaves runtime-dynamic `import(url)` untouched in IIFE output
- [ ] New `frontend/src/toolbar/loader.ts`: capture `document.currentScript.src` as base; synchronously define `ph_load_toolbar`/`ph_load_editor`/forwarding `posthogToolbarController` stub; on first call `import()` the entry with retry/backoff (copy the pattern from `frontend/src/lib/utils/retryImport.ts` — do NOT import app code); on failure fall back once to hashless `toolbar/toolbar-app.js?t={5-min bucket}`, then degrade to no-toolbar with `console.warn`
- [ ] `frontend/src/toolbar/index.tsx`: `export async function loadToolbar(...)` + export controller (keep window assigns for back-compat); drop the IIFE `globalName`/banner-footer wrapper (`__posthogToolbarModule` is referenced by nothing)
- [ ] Same PR (or CI reds) — `frontend/bin/check-toolbar-size.mjs`: per-file 10MB gzip limit across all toolbar outputs; **eager-set budget** (entry + transitive `kind: 'import-statement'` closure from the metafile, same traversal as `writePreloadManifest` in `build.mjs`; start ~10% above baseline); loader < ~20KB
- [ ] Same PR — `frontend/bin/check-toolbar-csp-eval.mjs`: glob all toolbar JS outputs; assert loader = 0 `new Function`, eager closure = 1 (the `toolbarLogic.ts` CSP probe), total = 5 (4 pixi move into the hedgehog chunk)
- [ ] Assert exactly one CSS output in the metafile
- [ ] Parity gates: toolbar end-to-end on local app via `hogli start` (authorize flow, tabs, hedgehog chunk loads on demand, CSS in shadow root); Playwright page with strict CSP (`'nonce-…' 'strict-dynamic'`, and separately host-allowlist) + posthog-js loading `dist/toolbar.js` → shadow root mounts; pin an OLD posthog-js version against the new dist to prove the contract; `Toolbar.stories.tsx` green

Done when: ~30% of the bundle is deferred with no source changes and all guards are green. Known-unsupported: exact-path CSP allowlists (`script-src .../toolbar.js`) — document in the PR.

### Step 3 — toolbar-owned `urls` duplicate (landed before Step 2, see reorder note)

Approach (revised on review): rather than restructuring the generated products manifest so `scenes/urls` stops dragging it in, the toolbar gets its own deliberately duplicated `frontend/src/toolbar/urls.ts` with only the url helpers it links to, and a parity test keeps it honest. A first version of this PR split `products-urls.tsx` out of the generator; that was reverted as over-engineered — the duplicate + test is simpler to review and keeps the generator untouched.

- [x] `frontend/src/toolbar/urls.ts`: the 12 helpers toolbar code uses (`action(s)`, `experiment(s)`, `featureFlag(s)`, `productTour`, `sessionProfile`, `settings`, `survey(s)`, `webAnalyticsWebVitals`), plus a documented `urlToResource` null stub (the real one walks a matcher tree built from every product manifest; its only toolbar-shipped consumer is Link's drag-to-notebook annotation, inert on customer pages)
- [x] `frontend/src/toolbar/urls.test.ts`: parity test asserting each helper matches `scenes/urls` byte-for-byte over sample args (the test deliberately crosses the boundary — that's its job); a helper without samples fails
- [x] All 11 toolbar files import `~/toolbar/urls`; their `-> src/scenes/urls.ts` baseline edges are deleted (47 → 36)
- [x] The 3 lib files shipped in the toolbar (`TZLabel`, `HeatmapEventsPanel`, `Link`) still import `scenes/urls` — they're shared with the app and can't be repointed; the third PR's `scenes/urls` shim resolves them to the toolbar duplicate at build time, removing their edges and taking `scenes/urls` + the products manifest out of the toolbar graph entirely
- [ ] Verify the app/exporter eager-graph improvements with the `check-eager-graph` owners

### Step 4 — `~/types` hygiene

- [ ] Convert type-only imports in `frontend/src/types.ts` to `import type`; make `lib/Chart` type-only
- [ ] Drop the runtime `export { SnapshotSourceType } from '@posthog/replay-shared'` re-export (kills the `hls.js` deny); import it from a leaf module where used
- [ ] Move genuine leaf enums (`SessionRecordingPlayerMode`, `WEB_SAFE_FONTS`, ...) to leaf modules; update importers
- [ ] Optional: oxlint `typescript/consistent-type-imports` on types.ts
- [ ] Shrink allowlist + drop retired deny entries (`hls.js`, half of `chart.js`)

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
