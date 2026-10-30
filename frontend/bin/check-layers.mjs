#!/usr/bin/env node
// Blocks a new static import from a lower frontend layer into a higher one (see layers.mjs).
//
//   node frontend/bin/check-layers.mjs                    check against the baseline
//   node frontend/bin/check-layers.mjs --prune-baseline   drop fixed entries, never add one
//   node frontend/bin/check-layers.mjs --update-baseline  rewrite the baseline, new debt included
//   node frontend/bin/check-layers.mjs --html <file>      write an interactive view of the graph
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { esbuildBuild } from '@posthog/esbuilder'

import { AUTHENTICATED_SHELL, BOOT_ENTRIES } from './bootEntries.mjs'
import { renderLayerGraphHtml } from './layerGraphHtml.mjs'
import { findOpportunities } from './layerOpportunities.mjs'
import { LAYERS, isUpward, layerOf } from './layers.mjs'

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const baselinePath = path.join(repoRoot, 'frontend', 'bin', 'layer-baseline.txt')
const BASELINE_HEADER = `# Static imports from a lower frontend layer into a higher one (see frontend/bin/layers.mjs).
# Grandfathered debt: the check fails on an upward import that is NOT listed here.
#
# DO NOT EDIT BY HAND. Mechanical output of \`hogli lint:frontend-layers --update-baseline\`.
# Fixed one? Run \`hogli lint:frontend-layers --prune-baseline\` to drop it.
`

// Path aliases resolve through tsconfig; anything else that is not relative is a package, and packages
// are outside the layer map.
const ALIAS_PREFIXES = ['lib/', 'scenes/', '~/', 'products/', 'public/', '@posthog/', '@common/']
const ASSET_EXTENSIONS = [
    '.css',
    '.scss',
    '.svg',
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.webp',
    '.avif',
    '.ico',
    '.woff',
    '.woff2',
    '.ttf',
    '.otf',
    '.eot',
    '.mp3',
    '.mp4',
    '.wav',
    '.ogg',
    '.lottie',
    '.riv',
    '.json',
    '.md',
    '.txt',
    '.html',
    '.yaml',
    '.yml',
    '.csv',
    '.wasm',
    '.bin',
    '.gz',
    '.zip',
    '.glb',
    '.gltf',
]

const externalizePackages = {
    name: 'externalize-packages',
    setup(build) {
        build.onResolve({ filter: /\?[a-z]+$/ }, (args) => ({ path: args.path, external: true }))
        build.onResolve({ filter: /^[^./]/ }, async (args) => {
            if (args.pluginData?.resolvingAlias) {
                return undefined
            }
            if (ALIAS_PREFIXES.some((prefix) => args.path.startsWith(prefix))) {
                const resolved = await build.resolve(args.path, {
                    kind: args.kind,
                    resolveDir: args.resolveDir,
                    importer: args.importer,
                    pluginData: { resolvingAlias: true },
                })
                if (!resolved.errors.length && !resolved.path.includes('/node_modules/')) {
                    return resolved
                }
            }
            return { path: args.path, external: true }
        })
    },
}

async function readImportGraph() {
    const result = await esbuildBuild({
        absWorkingDir: repoRoot,
        entryPoints: BOOT_ENTRIES.map((entry) => `frontend/${entry}`),
        tsconfig: path.join(repoRoot, 'tsconfig.json'),
        bundle: true,
        splitting: true,
        format: 'esm',
        jsx: 'automatic',
        write: false,
        metafile: true,
        outdir: path.join(repoRoot, 'frontend', '.layer-check-out'),
        logLevel: 'silent',
        loader: Object.fromEntries(ASSET_EXTENSIONS.map((extension) => [extension, 'empty'])),
        plugins: [externalizePackages],
    })
    const files = {}
    for (const [file, input] of Object.entries(result.metafile.inputs)) {
        files[file] = {
            bytes: input.bytes,
            staticImports: input.imports.filter((i) => i.kind === 'import-statement' && !i.external).map((i) => i.path),
        }
    }
    return files
}

function staticReach(files, root) {
    const parentOf = new Map([[root, null]])
    const queue = [root]
    while (queue.length) {
        const file = queue.shift()
        for (const target of files[file]?.staticImports ?? []) {
            if (!parentOf.has(target)) {
                parentOf.set(target, file)
                queue.push(target)
            }
        }
    }
    return parentOf
}

function chainTo(parentOf, file) {
    const chain = []
    for (let current = file; current; current = parentOf.get(current)) {
        chain.unshift(current)
    }
    return chain
}

function upwardImports(files) {
    const edges = []
    for (const [from, { staticImports }] of Object.entries(files)) {
        for (const to of staticImports) {
            if (isUpward(from, to)) {
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

const args = process.argv.slice(2)
const htmlIndex = args.indexOf('--html')

const files = await readImportGraph()
const shellRoot = `frontend/${AUTHENTICATED_SHELL}`
const shellReach = staticReach(files, shellRoot)
const current = upwardImports(files)
const baseline = readBaseline()
const added = current.filter((edge) => !baseline.includes(edge))
const fixed = baseline.filter((edge) => !current.includes(edge))

const mib = (bytes) => `${(bytes / 2 ** 20).toFixed(2)} MiB`
const eager = eagerBytesByLayer(files, shellReach)
console.info(
    `Upward imports: ${current.length} (${baseline.length} in the baseline, ${added.length} new, ${fixed.length} fixed)`
)
console.info(
    `Shell eager graph by layer (source bytes): ${LAYERS.map((layer) => `${layer} ${mib(eager[layer])}`).join(', ')}`
)

if (htmlIndex !== -1) {
    const htmlPath = path.resolve(args[htmlIndex + 1])
    const opportunities = findOpportunities({ files, shellRoot, shellReach })
    fs.writeFileSync(
        htmlPath,
        renderLayerGraphHtml({ files, shellRoot, shellReach, upward: current, layerOf, layers: LAYERS, opportunities })
    )
    console.info(`Wrote ${htmlPath}`)
}

if (args.includes('--update-baseline')) {
    writeBaseline(current)
    console.info(`Baseline rewritten with ${current.length} entries.`)
    process.exit(0)
}
if (args.includes('--prune-baseline')) {
    writeBaseline(baseline.filter((edge) => current.includes(edge)))
    console.info(`Dropped ${fixed.length} fixed entries.`)
    fixed.length = 0
}

for (const edge of added) {
    const [from, to] = edge.split(' -> ')
    console.info(`\nNew upward import, ${layerOf(from)} -> ${layerOf(to)}:\n  ${edge}`)
    if (shellReach.has(from)) {
        console.info(
            `  It puts ${layerOf(to)} code on the eager path of every logged-in page:\n    ${chainTo(shellReach, from).join('\n    -> ')}`
        )
    }
    console.info(
        `  Load it with lazyWithRetry() or retryImport(() => import(...)), or move the shared code down a layer.`
    )
}
if (fixed.length) {
    console.info(
        `\n${fixed.length} baseline entries are fixed. Run \`hogli lint:frontend-layers --prune-baseline\` to lock in the win.`
    )
}
process.exit(added.length || fixed.length ? 1 : 0)
