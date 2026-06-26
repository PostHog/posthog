# Storybook builder: webpack5 → Vite (WIP)

Migrates the builder from `@storybook/react-webpack5` to
`@storybook/react-vite`. The hard blocker is solved and stories render;
remaining work is mechanical CJS→ESM cleanup.

## What works

- `main.ts` uses `@storybook/react-vite` + a `viteFinal` porting the old
  `webpack.config.js`: monorepo + `frontend/node_modules` aliases (Vite has
  no `resolve.modules`), react/kea `dedupe`, `@tailwindcss/vite`, buffer/global.
- The webpack `ModuleGraphPlugin` (CI story-selection via `module-graph.json`)
  is reimplemented as a Rollup plugin; `.sql` raw imports get a small plugin.
- Dev boots in seconds, ~2144 stories index, and stories render — verified
  `lemon-toast`, `HogQLEditor`, the survey scene, and Max, with no errors.

## The blocker, and how it was found

Symptom: the iframe's query-less `/.storybook/preview.tsx` import returned 404
(the same URL with any `?query` served fine), so nothing rendered. A fresh
isolated `react-vite` storybook worked; this monorepo did not.

Root cause: `common/storybook/babel.config.js`. It was the old webpack
`babel-loader` config. Vite uses esbuild for JSX/TS, but Vite/Rollup still
auto-discovers a root `babel.config.js` and routes transforms through Babel —
and that path (`@babel/preset-env` `useBuiltIns: 'usage'` injecting core-js)
broke query-less serving. Deleting it fixed the 404. The `@babel/*` deps
dropped from `package.json` only existed for that file.

Next layer: `require is not defined` — source files using CommonJS `require()`,
which Vite's ESM lacks.

## CJS→ESM conversion (done)

All Storybook-bundled `require()` calls are converted to top-level imports:

- `frontend/src/mocks/handlers.ts` — fixture requires → ESM imports.
- 30 story files that `require('….json')` fixtures — hoisted to
  `import x from './….json'`. Because `require()` returned `any` but a typed
  JSON import does not, each fixture binding is cast `as any` at use (matches
  the existing `as any` / `as unknown as …` idiom in `InsightCard.stories.tsx`)
  so the fixtures stay loosely typed exactly as before.
- 3 error-tracking stories — `require('…/batch_get')` → named import
  `{ results }` passed as the mock body.

Left intentionally (not Storybook-bundled, or not a real import):
`frontend/src/test/insight-testing/render-insight.tsx` (jest-only require that
breaks a circular-dep cycle), `EndpointPlayground.tsx` (require inside a
template-string code sample), and a `types.ts` comment.

A few more webpack-isms (`require.context`, `module.hot`) may surface as more
stories load — same fix pattern.

## Before merging

- Expect a full VR re-baseline (bundler change shifts CSS/asset output); do it
  as one approved baseline, not interleaved with feature changes.
- Sanity-check the app under the `vite: 7.3.5` override:
  `pnpm --filter=@posthog/frontend build`.
