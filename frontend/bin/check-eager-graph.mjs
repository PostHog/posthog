#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const metaPath = path.join(frontendDir, 'posthog-app-esbuild-meta.json')

// The eager graph is everything reachable from a root through STATIC imports only —
// the code a browser must download and decode before that surface is interactive,
// regardless of how the bytes are distributed across chunks. Total dist size can't
// see regressions here (a fake-lazy require() moves no bytes, but makes them eager),
// which is why this check exists alongside the compressed-size check.
//
// Budgets are input-source bytes (pre-minification): stable across builds and
// proportional to decoded-script memory cost per renderer (see #32479).
// Ratchet policy: when a bundle-splitting win lands, lower the budget to lock it in;
// raise a budget only as a conscious, reviewed decision in the PR that needs it.
const ROOTS = [
    {
        root: 'src/index.tsx',
        label: 'entry (logged-out pages, app bootstrap)',
        budgetBytes: 16_500_000,
        forbidden: ['node_modules/monaco-editor/'],
    },
    {
        root: 'src/scenes/AuthenticatedShell.tsx',
        label: 'authenticated shell (every logged-in page)',
        budgetBytes: 64_000_000,
        forbidden: [],
    },
]

function fail(message) {
    console.error(`\n❌ ${message}`)
    process.exitCode = 1
}

function formatMB(bytes) {
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function eagerClosure(inputs, root) {
    const parentOf = new Map()
    const seen = new Set([root])
    const queue = [root]
    while (queue.length) {
        const file = queue.shift()
        for (const imp of inputs[file]?.imports || []) {
            if (imp.kind === 'dynamic-import' || seen.has(imp.path) || !inputs[imp.path]) {
                continue
            }
            seen.add(imp.path)
            parentOf.set(imp.path, file)
            queue.push(imp.path)
        }
    }
    return { seen, parentOf }
}

function chainTo(parentOf, target) {
    const chain = []
    let cur = target
    while (cur !== undefined && chain.length < 50) {
        chain.unshift(cur)
        cur = parentOf.get(cur)
    }
    return chain
}

if (!fs.existsSync(metaPath)) {
    fail(`Metafile not found at ${metaPath} — run \`pnpm --filter=@posthog/frontend build\` first.`)
    process.exit(1)
}

const inputs = JSON.parse(fs.readFileSync(metaPath, 'utf-8')).inputs
const summaryLines = ['## Eager graph check', '', '| Root | Eager size | Budget | Files |', '| --- | --- | --- | --- |']

for (const { root, label, budgetBytes, forbidden } of ROOTS) {
    if (!inputs[root]) {
        const candidates = Object.keys(inputs)
            .filter((k) => k.endsWith(path.basename(root)))
            .slice(0, 5)
        fail(`Root '${root}' not found in metafile. Was it moved/renamed? Candidates: ${candidates.join(', ')}`)
        continue
    }

    const { seen, parentOf } = eagerClosure(inputs, root)
    let totalBytes = 0
    for (const file of seen) {
        totalBytes += inputs[file].bytes
    }

    const overBudget = totalBytes > budgetBytes
    const status = overBudget ? '❌' : '✅'
    console.info(`${status} ${label}`)
    console.info(`   root: ${root}`)
    console.info(`   eager closure: ${seen.size} files, ${formatMB(totalBytes)} (budget ${formatMB(budgetBytes)})`)
    summaryLines.push(`| ${status} \`${root}\` | ${formatMB(totalBytes)} | ${formatMB(budgetBytes)} | ${seen.size} |`)

    if (overBudget) {
        const largest = [...seen]
            .map((f) => [f, inputs[f].bytes])
            .sort((a, b) => b[1] - a[1])
            .slice(0, 15)
        fail(
            `Eager graph for '${root}' is ${formatMB(totalBytes)}, over the ${formatMB(budgetBytes)} budget.\n` +
                `Something newly reachable through static imports is inflating it. Largest files in the closure:\n` +
                largest.map(([f, b]) => `   ${formatMB(b).padStart(9)}  ${f}`).join('\n') +
                `\nMake the offending import lazy (React.lazy / dynamic import()), or raise the budget in ` +
                `frontend/bin/check-eager-graph.mjs as a conscious decision in this PR.`
        )
    }

    for (const forbiddenSubstr of forbidden) {
        const hit = [...seen].find((f) => f.includes(forbiddenSubstr))
        if (hit) {
            fail(
                `'${forbiddenSubstr}' is statically reachable from '${root}' — it must stay behind a dynamic import.\n` +
                    `Import chain:\n   ${chainTo(parentOf, hit).join('\n   -> ')}`
            )
        }
    }
}

if (process.env.GITHUB_STEP_SUMMARY) {
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summaryLines.join('\n') + '\n')
}

if (process.exitCode) {
    console.error('\nEager graph check failed — see above.')
} else {
    console.info('\nAll eager graph budgets respected.')
}
