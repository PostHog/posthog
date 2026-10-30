#!/usr/bin/env node
// Blocks a new component that uses a stylesheet's block class (like `.PropertyFilters`) without importing
// that stylesheet. Such a component renders right only while some other module loads the CSS first, and it
// breaks without warning when that module moves off the page's import path (see cssCoupling.mjs).
//
//   node frontend/bin/check-css-coupling.mjs                    check against the baseline
//   node frontend/bin/check-css-coupling.mjs --prune-baseline   drop fixed entries, never add one
//   node frontend/bin/check-css-coupling.mjs --update-baseline  rewrite the baseline, new debt included
//   node frontend/bin/check-css-coupling.mjs --report-only      list every coupling, never fail
import fs from 'node:fs'
import path from 'node:path'

import { couplingKey, findCouplings } from './cssCoupling.mjs'
import { readImportGraph, repoRoot } from './importGraph.mjs'

const baselinePath = path.join(repoRoot, 'frontend', 'bin', 'css-coupling-baseline.txt')
const BASELINE_HEADER = `# Components that use a stylesheet's block class without importing the stylesheet (see frontend/bin/cssCoupling.mjs).
# Grandfathered debt: the check fails on a coupling that is NOT listed here.
#
# DO NOT EDIT BY HAND. Mechanical output of \`hogli lint:frontend-css-coupling --update-baseline\`.
# Fixed one? Run \`hogli lint:frontend-css-coupling --prune-baseline\` to drop it.
`

function readBaseline() {
    if (!fs.existsSync(baselinePath)) {
        return []
    }
    return fs
        .readFileSync(baselinePath, 'utf8')
        .split('\n')
        .filter((line) => line && !line.startsWith('#'))
}

function writeBaseline(keys) {
    fs.writeFileSync(baselinePath, BASELINE_HEADER + keys.map((key) => `${key}\n`).join(''))
}

const STYLESHEET_ROOTS = ['frontend/src', 'products']
const IGNORED_DIRS = new Set(['node_modules', 'dist', 'generated', '.turbo', '.layer-check-out'])

// Walks the filesystem rather than the import graph, so a stylesheet with no remaining importer is
// still indexed (see findCouplings in cssCoupling.mjs).
function walkStylesheets(dir, out = []) {
    const abs = path.join(repoRoot, dir)
    if (!fs.existsSync(abs)) {
        return out
    }
    for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
        const rel = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            if (!IGNORED_DIRS.has(entry.name)) {
                walkStylesheets(rel, out)
            }
        } else if (/\.s?css$/.test(entry.name)) {
            out.push(rel)
        }
    }
    return out
}

function describe({ file, className, stylesheets }) {
    return [
        `  ${file} uses .${className}, but does not import ${stylesheets.join(' or ')}.`,
        `  Import the stylesheet in ${path.basename(file)}, or replace .${className} with Tailwind classes.`,
    ].join('\n')
}

const args = process.argv.slice(2)
const files = await readImportGraph()
const stylesheetFiles = STYLESHEET_ROOTS.flatMap((root) => walkStylesheets(root))
const couplings = findCouplings(files, (file) => fs.readFileSync(path.join(repoRoot, file), 'utf8'), stylesheetFiles)
const current = [...new Set(couplings.map(couplingKey))].sort()
const baseline = readBaseline()
const added = couplings.filter((coupling) => !baseline.includes(couplingKey(coupling)))
const fixed = baseline.filter((key) => !current.includes(key))

console.info(
    `CSS couplings: ${current.length} (${baseline.length} in the baseline, ${added.length} new, ${fixed.length} fixed)`
)

if (args.includes('--report-only')) {
    for (const coupling of couplings) {
        console.info(`\n${describe(coupling)}`)
    }
    process.exit(0)
}
if (args.includes('--update-baseline')) {
    writeBaseline(current)
    console.info(`Baseline rewritten with ${current.length} entries.`)
    process.exit(0)
}
if (args.includes('--prune-baseline')) {
    writeBaseline(baseline.filter((key) => current.includes(key)))
    console.info(`Dropped ${fixed.length} fixed entries.`)
    fixed.length = 0
}

for (const coupling of added) {
    console.info(`\nNew CSS coupling:\n${describe(coupling)}`)
}
if (fixed.length) {
    console.info(
        `\n${fixed.length} baseline entries are fixed. Run \`hogli lint:frontend-css-coupling --prune-baseline\` to lock in the win.`
    )
}
process.exit(added.length || fixed.length ? 1 : 0)
