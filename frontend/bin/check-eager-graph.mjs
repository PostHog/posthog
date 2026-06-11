#!/usr/bin/env node
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const metaPath = path.join(frontendDir, 'posthog-app-esbuild-meta.json')

// --report-only: record results without failing the build. Used by build:with-report
// because compressed-size-action runs that script for BOTH the PR build and the base
// build — a base-branch budget breach must not abort the action for every open PR.
// Enforcement happens in the dedicated workflow step via --assert-report.
const reportOnly = process.argv.includes('--report-only')

// --assert-report <path>: skip measuring; read a previously written report and exit
// non-zero if it records violations.
const assertReportIndex = process.argv.indexOf('--assert-report')

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
        // master 2026-06-11: 14.59 MB / 749 files (post #62923)
        budgetBytes: 17_000_000,
        forbidden: ['node_modules/monaco-editor/'],
    },
    {
        root: 'src/scenes/AuthenticatedShell.tsx',
        label: 'authenticated shell (every logged-in page)',
        // master 2026-06-11: 55.51 MB / 8,325 files (ratchet down once #62957 / #62967 land)
        budgetBytes: 64_000_000,
        forbidden: [],
    },
]

function fail(message) {
    console.error(`\n❌ ${message}`)
    process.exitCode = 1
}

function assertReport(reportFilePath) {
    if (!fs.existsSync(reportFilePath)) {
        fail(`Report not found at ${reportFilePath} — did the build run the check?`)
        return
    }
    const reportToAssert = JSON.parse(fs.readFileSync(reportFilePath, 'utf-8'))
    for (const message of reportToAssert.errors ?? []) {
        fail(message)
    }
    for (const r of reportToAssert.roots) {
        if (r.overBudget) {
            fail(
                `Eager graph for '${r.root}' is ${formatMB(r.bytes)}, over the ${formatMB(r.budgetBytes)} budget.\n` +
                    `Largest files in the closure:\n` +
                    r.largest.map(({ file, bytes }) => `   ${formatMB(bytes).padStart(9)}  ${file}`).join('\n') +
                    `\nMake the offending import lazy (React.lazy / dynamic import()), or raise the budget in ` +
                    `frontend/bin/check-eager-graph.mjs as a conscious decision in this PR.`
            )
        }
        for (const hit of r.forbiddenHits) {
            fail(
                `'${hit.module}' is statically reachable from '${r.root}' — it must stay behind a dynamic import.\n` +
                    `Import chain:\n   ${hit.chain.join('\n   -> ')}`
            )
        }
        if (!process.exitCode) {
            console.info(`✅ ${r.label}: ${formatMB(r.bytes)} within ${formatMB(r.budgetBytes)}`)
        }
    }
}

if (assertReportIndex !== -1) {
    assertReport(process.argv[assertReportIndex + 1])
    if (process.exitCode) {
        console.error('\nEager graph check failed — see above.')
    } else {
        console.info('\nAll eager graph budgets respected.')
    }
    process.exit(process.exitCode ?? 0)
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
const report = { roots: [], errors: [] }

for (const { root, label, budgetBytes, forbidden } of ROOTS) {
    if (!inputs[root]) {
        const candidates = Object.keys(inputs)
            .filter((k) => k.endsWith(path.basename(root)))
            .slice(0, 5)
        const message = `Root '${root}' not found in metafile. Was it moved/renamed? Candidates: ${candidates.join(', ')}`
        report.errors.push(message)
        fail(message)
        continue
    }

    const { seen, parentOf } = eagerClosure(inputs, root)
    let totalBytes = 0
    for (const file of seen) {
        totalBytes += inputs[file].bytes
    }
    const largest = [...seen]
        .map((f) => [f, inputs[f].bytes])
        .sort((a, b) => b[1] - a[1])
        .slice(0, 15)

    const overBudget = totalBytes > budgetBytes
    const status = overBudget ? '❌' : '✅'
    console.info(`${status} ${label}`)
    console.info(`   root: ${root}`)
    console.info(`   eager closure: ${seen.size} files, ${formatMB(totalBytes)} (budget ${formatMB(budgetBytes)})`)
    summaryLines.push(`| ${status} \`${root}\` | ${formatMB(totalBytes)} | ${formatMB(budgetBytes)} | ${seen.size} |`)

    if (overBudget) {
        fail(
            `Eager graph for '${root}' is ${formatMB(totalBytes)}, over the ${formatMB(budgetBytes)} budget.\n` +
                `Something newly reachable through static imports is inflating it. Largest files in the closure:\n` +
                largest.map(([f, b]) => `   ${formatMB(b).padStart(9)}  ${f}`).join('\n') +
                `\nMake the offending import lazy (React.lazy / dynamic import()), or raise the budget in ` +
                `frontend/bin/check-eager-graph.mjs as a conscious decision in this PR.`
        )
    }

    const forbiddenHits = []
    for (const forbiddenSubstr of forbidden) {
        const hit = [...seen].find((f) => f.includes(forbiddenSubstr))
        if (hit) {
            const chain = chainTo(parentOf, hit)
            forbiddenHits.push({ module: forbiddenSubstr, chain })
            fail(
                `'${forbiddenSubstr}' is statically reachable from '${root}' — it must stay behind a dynamic import.\n` +
                    `Import chain:\n   ${chain.join('\n   -> ')}`
            )
        }
    }

    report.roots.push({
        root,
        label,
        bytes: totalBytes,
        files: seen.size,
        budgetBytes,
        overBudget,
        forbidden,
        forbiddenHits,
        largest: largest.map(([f, b]) => ({ file: f, bytes: b })),
    })
}

// Consumed by the workflow's comment + enforcement steps; written even on failure so
// the PR comment can show what went over. The filename carries the built tree's HEAD
// sha because compressed-size-action runs this for BOTH the PR build and the base
// build in the same workspace — a plain filename would be overwritten by the base
// build, making downstream steps report the wrong branch.
const serialized = JSON.stringify(report, null, 2)
fs.writeFileSync(path.join(frontendDir, 'eager-graph-report.json'), serialized)
try {
    const headSha = execSync('git rev-parse HEAD', { cwd: frontendDir, encoding: 'utf-8' }).trim()
    fs.writeFileSync(path.join(frontendDir, `eager-graph-report-${headSha}.json`), serialized)
} catch (err) {
    console.error(`Could not write sha-specific report: ${err.message}`)
}

if (process.env.GITHUB_STEP_SUMMARY) {
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summaryLines.join('\n') + '\n')
}

if (process.exitCode) {
    console.error('\nEager graph check failed — see above.')
    if (reportOnly) {
        console.error('Running with --report-only: violations recorded in the report, not failing the build.')
        process.exit(0)
    }
} else {
    console.info('\nAll eager graph budgets respected.')
}
