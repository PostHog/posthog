#!/usr/bin/env node
// Build the web workers into dist/ and keep them fresh, for the Vite dev server.
//
// Vite serves the app in dev but never builds these — they are separate esbuild bundles the app
// loads by URL from /static (which Vite proxies to Django, which serves dist/). Without this,
// dist/ has no worker files at all locally, every `new Worker(...)` 404s, and each caller quietly
// falls back to doing its work on the main thread. That hides exactly the jank the workers exist
// to prevent, and it only shows up in production.
//
// Pass --dev to watch. Entry points come from workers.config.mjs, shared with the production build.
import * as path from 'path'
import { fileURLToPath } from 'url'

import { buildInParallel } from '@posthog/esbuilder'

import { WORKER_ENTRIES } from '../workers.config.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')

await buildInParallel(
    WORKER_ENTRIES.map(({ name, entryPoint, outfileName }) => ({
        name,
        absWorkingDir: frontendDir,
        entryPoints: [entryPoint],
        outfile: path.resolve(frontendDir, 'dist', outfileName),
        bundle: true,
        format: 'esm',
        writeMetaFile: false,
    }))
)
