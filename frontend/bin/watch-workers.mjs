#!/usr/bin/env node
// Build the web workers into dist/ and keep them fresh, for the Vite dev server.
//
// Vite serves the app in dev but never builds these — they are separate esbuild bundles the app
// loads by URL from /static (which Vite proxies to Django, which serves dist/). Without this,
// dist/ has no worker files at all locally, every `new Worker(...)` 404s, and each caller quietly
// falls back to doing its work on the main thread. That hides exactly the jank the workers exist
// to prevent, and it only shows up in production.
//
// Pass --dev to watch. Pass --outdir <path> to build somewhere other than dist/ (Storybook
// builds them into its own static dir). Entry points come from workers.config.mjs, shared
// with the production build.
import * as path from 'path'
import { fileURLToPath } from 'url'

import { buildInParallel, copySnappyWASMFile } from '@posthog/esbuilder'

import { WORKER_ENTRIES } from '../workers.config.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')

const outdirFlagIndex = process.argv.indexOf('--outdir')
const outDir =
    outdirFlagIndex === -1
        ? path.resolve(frontendDir, 'dist')
        : path.resolve(process.cwd(), process.argv[outdirFlagIndex + 1])

// The decompression worker bundles snappy-wasm, which fetches snappy_bg.wasm next to the worker
// script at runtime. Without it the worker reports ready, then fails every decompression, so
// callers exercise a fallback path that production never reaches.
copySnappyWASMFile(frontendDir, outDir)

await buildInParallel(
    WORKER_ENTRIES.map(({ name, entryPoint, outfileName }) => ({
        name,
        absWorkingDir: frontendDir,
        entryPoints: [entryPoint],
        outfile: path.resolve(outDir, outfileName),
        // The app requests these by fixed name (e.g. /static/monacoEditorWorker.js), so the
        // output must not get the production content-hash suffix.
        entryNames: '[dir]/[name]',
        bundle: true,
        format: 'esm',
        writeMetaFile: false,
    }))
)
