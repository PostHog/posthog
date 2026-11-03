#!/usr/bin/env node
// Builds kea-wasm:
// 1. compiles crate/ to wasm32 and generates the bindings with wasm-bindgen,
// 2. embeds the module as base64, so that it loads synchronously in every bundler,
// 3. bundles src/ to dist/index.cjs.js and dist/index.esm.js.
import { execFileSync } from 'node:child_process'
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = dirname(fileURLToPath(import.meta.url))
const repo = join(root, '../..')
// This package is not a pnpm workspace member. It uses common/esbuilder's esbuild, and it bundles the
// same redux, reselect and use-sync-external-store copies that the kea package resolves.
const esbuild = createRequire(join(repo, 'common/esbuilder/package.json'))('esbuild')
const pnpmStore = join(repo, 'node_modules/.pnpm')
const keaDir = readdirSync(pnpmStore).find((d) => /^kea@4\.0\.0-pre\.6/.test(d))
if (!keaDir) {
    throw new Error('kea@4.0.0-pre.6 is not installed. Run pnpm install first.')
}
const keaDeps = join(pnpmStore, keaDir, 'node_modules')
const gen = join(root, 'gen')
const skipRust = process.argv.includes('--skip-rust')

if (!skipRust) {
    execFileSync(
        'cargo',
        ['build', '--release', '--target', 'wasm32-unknown-unknown', '--manifest-path', join(root, 'crate/Cargo.toml')],
        { stdio: 'inherit' }
    )
    execFileSync(
        'wasm-bindgen',
        [
            '--target',
            'web',
            '--weak-refs',
            '--out-dir',
            gen,
            join(root, 'crate/target/wasm32-unknown-unknown/release/kea_wasm_engine.wasm'),
        ],
        { stdio: 'inherit' }
    )
    // The module is always loaded with initSync(). Remove the async default path: it uses
    // import.meta, which CommonJS consumers such as Jest can not parse.
    const bindings = join(gen, 'kea_wasm_engine.js')
    writeFileSync(
        bindings,
        readFileSync(bindings, 'utf8').replace(/new URL\('kea_wasm_engine_bg\.wasm', import\.meta\.url\)/, 'undefined')
    )
    const wasm = readFileSync(join(gen, 'kea_wasm_engine_bg.wasm'))
    writeFileSync(join(gen, 'wasm-base64.js'), `export const wasmBase64 = ${JSON.stringify(wasm.toString('base64'))}\n`)
    writeFileSync(join(gen, 'wasm-base64.d.ts'), 'export declare const wasmBase64: string\n')
}

mkdirSync(join(root, 'dist'), { recursive: true })
const shared = {
    entryPoints: [join(root, 'src/index.ts')],
    bundle: true,
    platform: 'neutral',
    target: 'es2020',
    // React must be the app's copy. Each consumer resolves it from frontend/node_modules.
    external: ['react', 'react/*'],
    nodePaths: [keaDeps],
    alias: { 'use-sync-external-store/shim': join(root, 'src/use-sync-external-store-shim.ts') },
    jsx: 'transform',
    logLevel: 'warning',
}
await esbuild.build({ ...shared, format: 'esm', outfile: join(root, 'dist/index.esm.js') })
await esbuild.build({ ...shared, format: 'cjs', outfile: join(root, 'dist/index.cjs.js') })
console.log('kea-wasm built')
