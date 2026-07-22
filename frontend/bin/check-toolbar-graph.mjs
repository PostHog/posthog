#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const metaPath = path.join(frontendDir, 'toolbar-esbuild-meta.json')
const baselinePath = path.join(__dirname, 'toolbar-graph-baseline.json')

// The toolbar runs on customer pages, so its bundle must only contain what the toolbar
// actually needs — not the app's scene graph. This check enforces that boundary from the
// esbuild metafile's INPUT graph (which is identical for dev and prod builds):
//
// 1. "Survivors" are the modules still reachable from the toolbar entry when traversal
//    refuses to walk INTO the app zone (scenes/, layout/, models/, products manifests).
//    Every survivor edge that crosses into the app zone is a real dependency the toolbar
//    code holds on the app. New crossing edges fail; cutting an edge means deleting it from
//    the checked-in baseline so the win is locked in.
//    Non-survivor crossings (app-zone code importing more app-zone code) aren't listed:
//    they disappear on their own when the last survivor edge into their family is cut.
//
// 2. Packages on the toolbar denylist (toolbar-config.mjs) must stay absent entirely —
//    their presence means the deny plugin regressed.
//
// This check enforces the module BOUNDARY only; it does not measure or gate on size. Shipped
// size is owned by check-toolbar-size.mjs, measured from the esbuild OUTPUT (post-tree-shake)
// and surfaced in the shared CI comment — the right place to look at toolbar size. Input-graph
// source bytes count code that tree-shakes away, so this check deliberately reports no byte size.
const ENTRY = 'src/toolbar/index.tsx'

const APP_ZONE = [/^src\/products/, /^src\/scenes\//, /^src\/layout\//, /^src\/models\//, /^\.\.\/products\//]

// Packages the toolbar never renders and must not appear in its graph at all. None have an
// import path into the toolbar today; this guard fails the build if a change reintroduces one.
const FORBIDDEN_PACKAGES = [
    'node_modules/monaco-editor/',
    'node_modules/chart.js/',
    'node_modules/mermaid/',
    'node_modules/hls.js/',
]

function fail(message) {
    console.error(`\n❌ ${message}`)
    process.exitCode = 1
}

if (!fs.existsSync(metaPath)) {
    fail(`Metafile not found at ${metaPath} — run \`pnpm --filter=@posthog/frontend build\` first.`)
    process.exit(1)
}

const inputs = JSON.parse(fs.readFileSync(metaPath, 'utf-8')).inputs
if (!inputs?.[ENTRY]) {
    fail(`Toolbar entry '${ENTRY}' not found in ${metaPath} — was the entry point moved?`)
    process.exit(1)
}

const baseline = JSON.parse(fs.readFileSync(baselinePath, 'utf-8'))
const baselineEdges = new Set(baseline.edges)

const inZone = (p) => APP_ZONE.some((re) => re.test(p))

// Survivor closure: reachable from the entry without walking into the app zone.
const survivors = new Set([ENTRY])
const queue = [ENTRY]
while (queue.length) {
    const file = queue.shift()
    for (const imp of inputs[file].imports || []) {
        if (!imp.path || !inputs[imp.path] || survivors.has(imp.path) || inZone(imp.path)) {
            continue
        }
        survivors.add(imp.path)
        queue.push(imp.path)
    }
}

const crossingEdges = new Set()
for (const file of survivors) {
    for (const imp of inputs[file].imports || []) {
        if (imp.path && inZone(imp.path)) {
            crossingEdges.add(`${file} -> ${imp.path}`)
        }
    }
}

const newEdges = [...crossingEdges].filter((e) => !baselineEdges.has(e)).sort()
const removedEdges = [...baselineEdges].filter((e) => !crossingEdges.has(e)).sort()

if (newEdges.length) {
    fail(
        `${newEdges.length} new toolbar -> app import edge(s):\n` +
            newEdges.map((e) => `   ${e}`).join('\n') +
            `\nThe toolbar bundle must not grow new dependencies on app code (scenes/, layout/, models/, ` +
            `products manifests) — it ships to customer pages. Import from lib/, move the shared code out ` +
            `of the app zone, or fetch via toolbarFetch instead.`
    )
}

if (removedEdges.length) {
    fail(
        `${removedEdges.length} baseline edge(s) no longer exist — delete them from ` +
            `frontend/bin/toolbar-graph-baseline.json in this PR to lock the win in:\n` +
            removedEdges.map((e) => `   ${e}`).join('\n')
    )
}

const forbiddenHits = FORBIDDEN_PACKAGES.filter((pkg) => Object.keys(inputs).some((k) => k.includes(pkg)))
for (const pkg of forbiddenHits) {
    fail(
        `'${pkg}' is present in the toolbar graph. It is on the toolbar denylist ` +
            `(frontend/toolbar-config.mjs) and must never be bundled — did the deny plugin regress?`
    )
}

const status = process.exitCode ? '🟡' : '🟢'
console.info(
    `${status} toolbar graph boundary: ${crossingEdges.size} toolbar -> app crossing edge(s) ` +
        `(baseline ${baselineEdges.size}), ${survivors.size} survivor files reachable from the entry`
)

if (process.env.GITHUB_STEP_SUMMARY) {
    fs.appendFileSync(
        process.env.GITHUB_STEP_SUMMARY,
        [
            '## Toolbar graph check',
            '',
            '| Metric | Value |',
            '| --- | --- |',
            `| ${status} toolbar -> app crossing edges | ${crossingEdges.size} (baseline ${baselineEdges.size}) |`,
            `| survivor files (toolbar-owned closure) | ${survivors.size} |`,
        ].join('\n') + '\n'
    )
}

if (process.exitCode) {
    console.error('\nToolbar graph check failed — see above.')
} else {
    console.info('\nToolbar graph boundary respected.')
}
