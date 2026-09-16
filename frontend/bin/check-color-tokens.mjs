#!/usr/bin/env node
/**
 * Fails when a `--color-product-*` custom property is referenced but never defined.
 *
 * These tokens are the one colour family named as plain strings from TypeScript, in product
 * manifests and empty-state configs, so nothing type-checks them. A reference to a token that
 * does not exist fails silently and completely: an undefined custom property makes every
 * `color-mix()` reading it invalid at computed-value time, so the browser drops those
 * declarations rather than falling back, and a whole surface renders with no colour.
 *
 * Also fails on a token defined but referenced nowhere, usually a rename left half done.
 *
 * Usage: node frontend/bin/check-color-tokens.mjs
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const TOKEN = /--color-product-[a-z0-9-]+/g
const DEFINITION = /(--color-product-[a-z0-9-]+)\s*:/g

// Roots to scan. Definitions may live in any app stylesheet, so the definition scan stays broad:
// moving the token block out of base.scss must not turn into a wave of false failures.
const DEFINITION_ROOTS = ['frontend/src/styles']
const DEFINITION_EXTS = ['.scss', '.css']
const REFERENCE_ROOTS = ['frontend/src', 'products']
const REFERENCE_EXTS = ['.ts', '.tsx', '.scss', '.css']
// Generated from the manifests, so a finding here is always a duplicate of the manifest's own.
// The desktop app is a separate workspace with its own tokens.
const IGNORED = ['frontend/src/products.tsx']
const IGNORED_DIRS = new Set(['node_modules', 'dist', 'generated', 'desktop', '.turbo'])

function walk(dir, exts, out = []) {
    const abs = path.join(REPO_ROOT, dir)
    if (!fs.existsSync(abs)) {
        return out
    }
    for (const entry of fs.readdirSync(abs, { withFileTypes: true })) {
        const rel = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            if (!IGNORED_DIRS.has(entry.name)) {
                walk(rel, exts, out)
            }
        } else if (exts.includes(path.extname(entry.name)) && !IGNORED.includes(rel)) {
            out.push(rel)
        }
    }
    return out
}

const filesFor = (roots, exts) => roots.flatMap((r) => walk(r, exts))

const defined = new Set()
for (const file of filesFor(DEFINITION_ROOTS, DEFINITION_EXTS)) {
    const src = fs.readFileSync(path.join(REPO_ROOT, file), 'utf8')
    for (const [, token] of src.matchAll(DEFINITION)) {
        defined.add(token)
    }
}

/** token -> the files that reference it */
const referenced = new Map()
for (const file of filesFor(REFERENCE_ROOTS, REFERENCE_EXTS)) {
    const src = fs.readFileSync(path.join(REPO_ROOT, file), 'utf8')
    for (const match of src.matchAll(TOKEN)) {
        // A definition is a reference to itself; skip so a stylesheet doesn't self-satisfy.
        if (src.slice(match.index + match[0].length).startsWith(':')) {
            continue
        }
        if (!referenced.has(match[0])) {
            referenced.set(match[0], new Set())
        }
        referenced.get(match[0]).add(file)
    }
}

const dangling = [...referenced.keys()].filter((t) => !defined.has(t)).sort()
const unused = [...defined].filter((t) => !referenced.has(t)).sort()

console.info(`${defined.size} product colour tokens defined, ${referenced.size} referenced`)

if (dangling.length) {
    console.error(`\n${dangling.length} token(s) referenced but never defined:`)
    for (const token of dangling) {
        console.error(`  ${token}`)
        for (const file of [...referenced.get(token)].sort()) {
            console.error(`      ${file}`)
        }
    }
    console.error('\nDefine them in frontend/src/styles/base.scss, or drop the reference.')
}

if (unused.length) {
    console.error(`\n${unused.length} token(s) defined but referenced nowhere:`)
    for (const token of unused) {
        console.error(`  ${token}`)
    }
    console.error('\nReference them, or remove them from frontend/src/styles/base.scss.')
}

const failed = dangling.length > 0 || unused.length > 0
if (!failed) {
    console.info('No dangling or unused product colour tokens.')
}
process.exit(failed ? 1 : 0)
