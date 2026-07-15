/**
 * Bundles the desktop app's three contexts with esbuild:
 *   dist/main.cjs         - Electron main process (CJS, Node)
 *   dist/preload.cjs      - preload script (CJS, sandboxed)
 *   dist/shell/shell.js   - shell UI script (IIFE, browser) + copied index.html
 */

import * as esbuild from 'esbuild'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const common = {
    bundle: true,
    sourcemap: true,
    logLevel: 'info',
    absWorkingDir: __dirname,
}

await esbuild.build({
    ...common,
    entryPoints: ['src/main/index.ts'],
    outfile: 'dist/main.cjs',
    platform: 'node',
    format: 'cjs',
    target: 'node22',
    external: ['electron'],
})

await esbuild.build({
    ...common,
    entryPoints: ['src/preload/index.ts'],
    outfile: 'dist/preload.cjs',
    platform: 'node',
    format: 'cjs',
    target: 'node22',
    external: ['electron'],
})

await esbuild.build({
    ...common,
    entryPoints: ['src/shell/shell.ts'],
    outfile: 'dist/shell/shell.js',
    platform: 'browser',
    format: 'iife',
    target: 'es2022',
})

fs.mkdirSync(path.join(__dirname, 'dist/shell'), { recursive: true })
fs.copyFileSync(path.join(__dirname, 'src/shell/index.html'), path.join(__dirname, 'dist/shell/index.html'))
