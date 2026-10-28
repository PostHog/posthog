# Real bundler output

The parity scenarios run both CLIs on these files, so hog is held to what posthog-cli does with real builds and not only with hand-written cases.

They were built from a small app (`index.js` importing `cart.js` and `ui/badge.js`, with a dynamic import of `reviews.js`) with:

| Folder        | Bundler        | Settings                                                                 |
| ------------- | -------------- | ------------------------------------------------------------------------ |
| `esbuild`     | esbuild 0.28   | ESM, code splitting, minified, hashed names, `sourcemap: 'linked'`       |
| `esbuild-cjs` | esbuild 0.28   | CommonJS, `sourcemap: 'external'`, so the map is found by its file name   |
| `rollup`      | rollup 4.60    | ESM, hashed `.mjs` chunks, `sourcemapDebugIds: true`                      |
| `terser`      | rollup + terser 5.46 | IIFE minified by terser, with the rollup map as input              |
| `webpack`     | webpack 5.105  | production mode, `devtool: 'source-map-debugids'`                         |

Do not edit them by hand: the goldens in `golden/e2e/` were recorded from these exact bytes.
