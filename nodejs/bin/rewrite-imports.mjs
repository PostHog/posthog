#!/usr/bin/env node
/**
 * Import-rewriting codemod for the ingestion-separation refactor.
 *
 * Given one or more `oldDir:newDir` mappings (paths relative to src/), it rewrites
 * every import across src/ and tests/ whose target is being moved so it points at
 * the new location using the move-stable `~/` alias.
 *
 * Run this BEFORE `git mv`: it edits files in place at their current paths, then the
 * physical move is safe because every affected import is now alias-based
 * (location-independent). Imports internal to a single moved directory are left as
 * relative paths (they move together, so they stay correct).
 *
 * Usage:
 *   node bin/rewrite-imports.mjs ingestion/outputs:common/outputs            # dry run
 *   node bin/rewrite-imports.mjs ingestion/outputs:common/outputs --apply    # write
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SRC = path.join(ROOT, 'src')
const TESTS = path.join(ROOT, 'tests')

const apply = process.argv.includes('--apply')
const pairs = process.argv.slice(2).filter((a) => !a.startsWith('--'))
if (pairs.length === 0) {
    console.error('Usage: rewrite-imports.mjs <oldRel:newRel>... [--apply]')
    process.exit(1)
}

const MAP = pairs.map((p) => {
    const [oldRel, newRel] = p.split(':')
    return { oldAbs: path.join(SRC, oldRel), newAbs: path.join(SRC, newRel) }
})

const SKIP_DIRS = new Set(['node_modules', 'dist', '__snapshots__'])

function walk(dir) {
    const out = []
    if (!fs.existsSync(dir)) {
        return out
    }
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
            if (!SKIP_DIRS.has(entry.name)) {
                out.push(...walk(path.join(dir, entry.name)))
            }
        } else if (entry.name.endsWith('.ts')) {
            out.push(path.join(dir, entry.name))
        }
    }
    return out
}

function mappingFor(absNoExt) {
    return MAP.find((m) => absNoExt === m.oldAbs || absNoExt.startsWith(m.oldAbs + path.sep))
}

function applyMove(absNoExt) {
    const m = mappingFor(absNoExt)
    return m ? m.newAbs + absNoExt.slice(m.oldAbs.length) : absNoExt
}

function aliasOf(absNoExt) {
    if (absNoExt === TESTS || absNoExt.startsWith(TESTS + path.sep)) {
        return '~/tests/' + path.relative(TESTS, absNoExt).split(path.sep).join('/')
    }
    return '~/' + path.relative(SRC, absNoExt).split(path.sep).join('/')
}

function resolveSpecifier(spec, importer) {
    if (spec.startsWith('~/tests/')) {
        return path.join(TESTS, spec.slice('~/tests/'.length))
    }
    if (spec.startsWith('~/')) {
        return path.join(SRC, spec.slice(2))
    }
    if (spec.startsWith('.')) {
        return path.resolve(path.dirname(importer), spec)
    }
    return null
}

const IMPORT_PATTERNS = [
    /\bfrom\s*['"]([^'"]+)['"]/g,
    /\bimport\s*['"]([^'"]+)['"]/g,
    /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g,
    /\brequire\(\s*['"]([^'"]+)['"]\s*\)/g,
]

function specifiersOf(source) {
    const specs = new Set()
    for (const re of IMPORT_PATTERNS) {
        re.lastIndex = 0
        let match
        while ((match = re.exec(source))) {
            specs.add(match[1])
        }
    }
    return specs
}

// Decide the replacement specifier for `spec` in file `importer`, or null to leave it.
function rewriteFor(spec, importer) {
    const target = resolveSpecifier(spec, importer)
    if (target === null) {
        return null
    }
    const mTarget = mappingFor(target)
    // Strip the importer's extension so file-level mappings (oldAbs has no extension) match it.
    const mImporter = mappingFor(importer.replace(/\.tsx?$/, ''))
    if (!mTarget && !mImporter) {
        return null // neither side moves
    }
    if (!mTarget && mImporter && spec.startsWith('~')) {
        return null // alias to a stable target survives the importer's move
    }
    if (mTarget && mImporter && mTarget === mImporter && spec.startsWith('.')) {
        return null // relative import internal to a single moved dir is preserved
    }
    const next = aliasOf(applyMove(target))
    return next === spec ? null : next
}

let filesChanged = 0
let editsTotal = 0
const samples = []

for (const file of [...walk(SRC), ...walk(TESTS)]) {
    let source = fs.readFileSync(file, 'utf8')
    let edits = 0
    for (const spec of specifiersOf(source)) {
        const next = rewriteFor(spec, file)
        if (!next) {
            continue
        }
        source = source.split(`'${spec}'`).join(`'${next}'`).split(`"${spec}"`).join(`"${next}"`)
        edits++
        if (samples.length < 12) {
            samples.push(`${path.relative(ROOT, file)}: ${spec} -> ${next}`)
        }
    }
    if (edits > 0) {
        filesChanged++
        editsTotal += edits
        if (apply) {
            fs.writeFileSync(file, source)
        }
    }
}

console.log(`${apply ? 'Rewrote' : 'Would rewrite'} ${editsTotal} import(s) across ${filesChanged} file(s).`)
for (const s of samples) {
    console.log(`  ${s}`)
}
if (!apply) {
    console.log('\n(dry run — pass --apply to write)')
}
