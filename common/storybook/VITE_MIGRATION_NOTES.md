# Storybook builder: webpack5 → Vite (WIP)

This branch migrates the Storybook builder from `@storybook/react-webpack5` to
`@storybook/react-vite`. The config port is **done**; one dependency-graph blocker remains.

## Status

- ✅ `main.ts` uses `@storybook/react-vite` + a `viteFinal` that ports the old 286-line
  `webpack.config.js`: monorepo + `frontend/node_modules` aliases (Vite has no
  `resolve.modules`), react/kea `dedupe`, `@tailwindcss/vite`, `buffer`/`global`.
- ✅ The webpack `ModuleGraphPlugin` (consumed by CI story-selection via
  `module-graph.json`) is reimplemented as a Rollup plugin
  (`.storybook/plugins/vite-module-graph-plugin.ts`) using Rollup `importers`.
- ✅ `.sql` raw imports get `vite-sql-raw-plugin.ts`. Dead `.less`/AntD/`.yaml` handling dropped.
- ✅ Dev server boots in seconds, **all ~2144 stories index**, and `preview.tsx` **transforms
  correctly** (valid module, all imports resolved).
- ❌ **Stories don't render.** The iframe's query-less import of `/.storybook/preview.tsx`
  returns **404** from Vite's `transformRequest` (the _same_ URL with any `?query` serves a
  perfect module). Nothing downstream loads, so the preview is empty ("No Preview").

## What the blocker is NOT (ruled out by bisection)

A fresh `@storybook/react-vite` + Vite 7.3.5 storybook in an isolated pnpm workspace
**renders fine**. The same versions inside this monorepo 404. Ruled out:

- the `viteFinal` config — a **minimal** config (no aliases/plugins) in the monorepo also 404s
- the Vite **plugin set** — byte-identical (15 plugins) between the fresh repro and the monorepo
- `@vitest/mocker` version — forcing 4.1.8 (vite-7 build) still 404s
- the **Vite version** — both the repro and the monorepo run **7.3.5**
- `@vitejs/plugin-react` — not an active plugin here (react-vite uses `storybook:react-docgen-plugin`)
- flox / node — system node also 404s
- Vite `root` / `server.fs.allow` / `base` — all correct (`root=common/storybook`, allow=repo root, base=`/`)

## What it IS (narrowed)

A **transitive sub-dependency version skew** unique to the monorepo. It carries multiple
copies of deps a fresh install collapses to one — `esbuild` (×5), `lightningcss` (×2), and
historically vite 5.4.21 / 6.4.2 pulled in by an older consumer (the `@tailwindcss/vite 4.2.2`
/ `sass-embedded` stack, e.g. quill's storybook). One of these makes an otherwise-identical
Vite pipeline return `null` from `transformRequest` for the query-less preview import.

The `pnpm.overrides` added here (`vite: 7.3.5`, `@vitest/mocker: 4.1.8`) are **directionally
correct groundwork** but were verified **insufficient** on their own.

## Suggested next step for manual debugging

1. Recreate the minimal failing case: a `.sbmin` config dir with a trivial `Button.stories.tsx`
   and an empty `preview.tsx`, run `storybook dev -c .sbmin`. It reproduces the 404 in seconds.
2. Add a `viteFinal` plugin with `configResolved(c) { writeFileSync('mono.json', JSON.stringify(c)) }`
   in BOTH a fresh isolated repro and here, then `diff` the two resolved configs. The one
   differing field (likely under `resolve`, `optimizeDeps`, or `esbuild`) is the lever.
3. Binary-search the transitive: collapse `esbuild` / `lightningcss` to single versions via
   scoped `pnpm.overrides`, or remove the vite-5/6-pulling consumer, until the minimal config renders.

Once it renders: expect a **full VR re-baseline** (bundler change shifts CSS/asset output) — do
it as one approved baseline, not interleaved with feature changes.
