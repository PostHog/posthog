#!/usr/bin/env node
// Measures the dashboard scene's "eager graph": the JS + CSS bytes a browser must download and
// parse before the dashboard surface is interactive. Same methodology as check-eager-graph.mjs
// (measured from the esbuild OUTPUT metafile, so tree-shaking is already accounted for), but
// rooted at the dashboard scene entry chunk instead of the app shell.
//
// Reports two numbers:
//   - total:    every chunk in the dashboard entry's eager closure (cold-load cost).
//   - marginal: the subset NOT already shipped by the authenticated shell — i.e. the extra
//               download when a logged-in user navigates into a dashboard. This is the honest
//               "dashboard loading time" proxy and the number the optimization loop minimizes.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const metaPath = path.join(frontendDir, 'posthog-app-esbuild-meta.json')

const DASHBOARD_ROOT = 'src/scenes/dashboard/Dashboard.tsx'
const SHELL_ROOT = 'src/scenes/AuthenticatedShell.tsx'

if (!fs.existsSync(metaPath)) {
    console.error(`Metafile not found at ${metaPath} — run \`pnpm --filter=@posthog/frontend build\` first.`)
    process.exit(1)
}

const meta = JSON.parse(fs.readFileSync(metaPath, 'utf-8'))
const outputs = meta.outputs
if (!outputs) {
    console.error(`Metafile has no "outputs" — rebuild with metafile output enabled.`)
    process.exit(1)
}

function entryChunk(root) {
    for (const [name, chunk] of Object.entries(outputs)) {
        if (chunk.entryPoint === root) {
            return name
        }
    }
    return null
}

// Eager closure: entry chunk + every chunk reachable through static (import-statement) chunk
// edges, plus each visited chunk's attached stylesheet (cssBundle, downloaded before render).
// dynamic-import edges are the lazy boundaries — stop there.
function eagerChunks(entry) {
    const seen = new Set([entry])
    const queue = [entry]
    const css = new Set()
    while (queue.length) {
        const chunk = queue.shift()
        const cssBundle = outputs[chunk].cssBundle
        if (cssBundle) {
            css.add(cssBundle)
        }
        for (const imp of outputs[chunk].imports || []) {
            if (imp.kind !== 'import-statement' || seen.has(imp.path) || !outputs[imp.path]) {
                continue
            }
            seen.add(imp.path)
            queue.push(imp.path)
        }
    }
    return { js: seen, css }
}

function sumBytes(chunkSet) {
    let total = 0
    for (const c of chunkSet) {
        total += outputs[c]?.bytes || 0
    }
    return total
}

const dashEntry = entryChunk(DASHBOARD_ROOT)
if (!dashEntry) {
    console.error(`Dashboard root '${DASHBOARD_ROOT}' is not an entry chunk — is it still a code-split boundary?`)
    process.exit(1)
}
const shellEntry = entryChunk(SHELL_ROOT)

const dash = eagerChunks(dashEntry)
const shell = shellEntry ? eagerChunks(shellEntry) : { js: new Set(), css: new Set() }

const totalJs = sumBytes(dash.js)
const totalCss = sumBytes(dash.css)
const total = totalJs + totalCss

// Marginal = dashboard eager chunks not already in the shell's eager closure.
const marginalJsChunks = [...dash.js].filter((c) => !shell.js.has(c))
const marginalCssChunks = [...dash.css].filter((c) => !shell.css.has(c))
const marginalJs = sumBytes(marginalJsChunks)
const marginalCss = sumBytes(marginalCssChunks)
const marginal = marginalJs + marginalCss

const kib = (b) => (b / 1024).toFixed(1)

// Largest marginal contributors, by the input modules that ship into the marginal chunks.
const marginalBytesByFile = new Map()
for (const c of [...marginalJsChunks, ...marginalCssChunks]) {
    for (const [file, info] of Object.entries(outputs[c].inputs || {})) {
        if (info.bytesInOutput > 0) {
            marginalBytesByFile.set(file, (marginalBytesByFile.get(file) || 0) + info.bytesInOutput)
        }
    }
}
const largest = [...marginalBytesByFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20)

console.info(`Dashboard eager graph (root ${DASHBOARD_ROOT}):`)
console.info(`  entry chunk:        ${dashEntry}`)
console.info(
    `  total eager:        ${kib(total)} KiB  (${kib(totalJs)} JS + ${kib(totalCss)} CSS, ${dash.js.size} JS chunks)`
)
console.info(
    `  marginal vs shell:  ${kib(marginal)} KiB  (${kib(marginalJs)} JS + ${kib(marginalCss)} CSS, ${marginalJsChunks.length} JS chunks)`
)
console.info(`\n  Largest marginal input modules:`)
for (const [file, bytes] of largest) {
    console.info(`    ${kib(bytes).padStart(9)} KiB  ${file}`)
}

// Machine-readable line for the loop harness.
console.info(
    `\nMETRIC total_kib=${kib(total)} marginal_kib=${kib(marginal)} total_bytes=${total} marginal_bytes=${marginal}`
)
