#!/usr/bin/env node
// Blocks a new static import from a lower frontend layer into a higher one (see layers.mjs).
//
//   node frontend/bin/check-layers.mjs                    check against the baseline
//   node frontend/bin/check-layers.mjs --prune-baseline   drop fixed entries, never add one
//   node frontend/bin/check-layers.mjs --update-baseline  rewrite the baseline, new debt included
//   node frontend/bin/check-layers.mjs --html <file>      write an interactive view of the graph
//   node frontend/bin/check-layers.mjs --report-only      write layer-report.json for the CI report, never fail
//   node frontend/bin/check-layers.mjs --from-report <f>  check a layer report against the baseline, no rebuild
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'

import { AUTHENTICATED_SHELL } from './bootEntries.mjs'
import { chainTo, isAssetPath, readImportGraph, repoRoot, staticReach } from './importGraph.mjs'
import { renderLayerGraphHtml } from './layerGraphHtml.mjs'
import { findOpportunities } from './layerOpportunities.mjs'
import { LAYERS, compareWithBaseline, isUpward, layerOf } from './layers.mjs'

const baselinePath = path.join(repoRoot, 'frontend', 'bin', 'layer-baseline.txt')
const BASELINE_HEADER = `# Static imports from a lower frontend layer into a higher one (see frontend/bin/layers.mjs).
# Grandfathered debt: the check fails on an upward import that is NOT listed here.
#
# DO NOT EDIT BY HAND. Mechanical output of \`hogli lint:frontend-layers --update-baseline\`.
# Fixed one? Run \`hogli lint:frontend-layers --prune-baseline\` to drop it.
`

function upwardImports(files) {
    const edges = []
    for (const [from, { staticImports }] of Object.entries(files)) {
        for (const to of staticImports) {
            if (!isAssetPath(to) && isUpward(from, to)) {
                edges.push(`${from} -> ${to}`)
            }
        }
    }
    return [...new Set(edges)].sort()
}

function readBaseline() {
    if (!fs.existsSync(baselinePath)) {
        return []
    }
    return fs
        .readFileSync(baselinePath, 'utf8')
        .split('\n')
        .filter((line) => line && !line.startsWith('#'))
}

function writeBaseline(edges) {
    fs.writeFileSync(baselinePath, BASELINE_HEADER + edges.map((edge) => `${edge}\n`).join(''))
}

function eagerBytesByLayer(files, reach) {
    const totals = Object.fromEntries(LAYERS.map((layer) => [layer, 0]))
    for (const file of reach.keys()) {
        totals[layerOf(file)] += files[file]?.bytes ?? 0
    }
    return totals
}

function eagerChainsOf(upward, shellReach) {
    return Object.fromEntries(
        upward
            .map((edge) => edge.split(' -> ')[0])
            .filter((from) => shellReach.has(from))
            .map((from) => [from, chainTo(shellReach, from)])
    )
}

// The CI build already writes this report, so CI checks it against the baseline without a second esbuild pass.
function readReport(reportPath) {
    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'))
    return { current: report.upward, eagerChains: report.eagerChains ?? {} }
}

const args = process.argv.slice(2)
const htmlIndex = args.indexOf('--html')
const fromReportIndex = args.indexOf('--from-report')

let current
let eagerChains
if (fromReportIndex !== -1) {
    ;({ current, eagerChains } = readReport(path.resolve(args[fromReportIndex + 1])))
} else {
    const files = await readImportGraph()
    const shellRoot = `frontend/${AUTHENTICATED_SHELL}`
    const shellReach = staticReach(files, shellRoot)
    current = upwardImports(files)
    eagerChains = eagerChainsOf(current, shellReach)

    const mib = (bytes) => `${(bytes / 2 ** 20).toFixed(2)} MiB`
    const eager = eagerBytesByLayer(files, shellReach)
    console.info(
        `Shell eager graph by layer (source bytes): ${LAYERS.map((layer) => `${layer} ${mib(eager[layer])}`).join(', ')}`
    )

    if (htmlIndex !== -1) {
        const htmlPath = path.resolve(args[htmlIndex + 1])
        const opportunities = findOpportunities({ files, shellRoot, shellReach })
        fs.writeFileSync(
            htmlPath,
            renderLayerGraphHtml({
                files,
                shellRoot,
                shellReach,
                upward: current,
                layerOf,
                layers: LAYERS,
                opportunities,
            })
        )
        console.info(`Wrote ${htmlPath}`)
    }

    // Same naming as check-eager-graph: the CI bundle-size job measures the PR and then the base in one
    // workspace, so the sha-suffixed file keeps the PR's numbers and the plain file ends up with the base's.
    if (args.includes('--report-only')) {
        const report = {
            sha: execSync('git rev-parse HEAD', { cwd: repoRoot, encoding: 'utf-8' }).trim(),
            layers: LAYERS,
            eagerBytes: eager,
            upward: current,
            eagerChains,
        }
        const serialized = JSON.stringify(report)
        fs.writeFileSync(path.join(repoRoot, 'frontend', 'layer-report.json'), serialized)
        fs.writeFileSync(path.join(repoRoot, 'frontend', `layer-report-${report.sha}.json`), serialized)
        process.exit(0)
    }
}

if (args.includes('--update-baseline')) {
    writeBaseline(current)
    console.info(`Baseline rewritten with ${current.length} entries.`)
    process.exit(0)
}
let baseline = readBaseline()
if (args.includes('--prune-baseline')) {
    const kept = baseline.filter((edge) => current.includes(edge))
    writeBaseline(kept)
    console.info(`Dropped ${baseline.length - kept.length} fixed entries.`)
    baseline = kept
}

const { added, fixed, failed, pruneHint } = compareWithBaseline(current, baseline)
console.info(
    `Upward imports: ${current.length} (${baseline.length} in the baseline, ${added.length} new, ${fixed.length} fixed)`
)
for (const edge of added) {
    const [from, to] = edge.split(' -> ')
    console.info(`\nNew upward import, ${layerOf(from)} -> ${layerOf(to)}:\n  ${edge}`)
    if (eagerChains[from]) {
        console.info(
            `  It puts ${layerOf(to)} code on the eager path of every logged-in page:\n    ${eagerChains[from].join('\n    -> ')}`
        )
    }
    console.info(
        `  Load it with lazyWithRetry() or retryImport(() => import(...)), or move the shared code down a layer.`
    )
}
if (pruneHint) {
    console.info(`\n${pruneHint}`)
    if (process.env.GITHUB_ACTIONS) {
        // A workflow command ends at the first newline, so GitHub needs %0A to keep the list in one annotation.
        console.info(`::error file=frontend/bin/layer-baseline.txt::${pruneHint.replaceAll('\n', '%0A')}`)
    }
}
process.exit(failed ? 1 : 0)
