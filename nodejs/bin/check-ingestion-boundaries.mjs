#!/usr/bin/env node
/**
 * Ingestion boundary guard.
 *
 * Enforces the ingestion-separation invariant during the cdp/ingestion refactor:
 *   - an ingestion pipeline must not import another pipeline's internals
 *   - shared/common ingestion code must not import a pipeline
 *   - no ingestion code may import cdp directly (ingestion and cdp meet only through common/)
 *   - no common/ code may import ingestion (common is the shared foundation, not a domain consumer)
 *
 * Import specifiers are resolved (tsconfig "~/*" alias + relative paths) to real
 * files, so cross-pipeline *relative* imports (e.g. `../heatmaps/x` from `analytics/`)
 * are caught — something a string-based eslint rule cannot reliably do.
 *
 * A baseline records the violations that already exist; the check fails only on
 * NEW violations. As the refactor removes edges, regenerate the baseline with
 * `--write` so it shrinks toward empty (an empty baseline = invariant achieved).
 *
 * Usage:
 *   node bin/check-ingestion-boundaries.mjs           # check against baseline
 *   node bin/check-ingestion-boundaries.mjs --write   # (re)generate the baseline
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const SRC = path.join(ROOT, 'src')
const ING = path.join(SRC, 'ingestion')
const CDP = path.join(SRC, 'cdp')
const COMMON = path.join(SRC, 'common')
const BASELINE = path.join(ROOT, 'bin', 'ingestion-boundaries.baseline.json')

// Ingestion pipelines — each is an isolated unit. A pipeline may not import another pipeline,
// and shared/common ingestion code may not import any pipeline.
const SHARED = '(shared)'
const PIPELINES = new Set([
    'analytics',
    'heatmaps',
    'clientwarnings',
    'ai',
    'errortracking',
    'sessionreplay',
    'metrics',
])

const SKIP_DIRS = new Set(['node_modules', 'dist', '__snapshots__'])

// The guard enforces the *production* import DAG. Test files (unit/integration/e2e) act as
// composition roots — they wire real implementations across domains (e.g. cdp's HogTransformer,
// the ai sub-pipeline factory) the same way the servers do — so they legitimately cross pipelines.
// Test-file organization is a separate concern, owned by Phase 3 ("split mixed tests").
const isTestFile = (name) => name.endsWith('.test.ts') || name.endsWith('.spec.ts')

// Composition roots assemble and run a pipeline — they wire pipelines together the way the
// servers do (e.g. ingestion-consumer builds and runs the analytics pipeline), so like the servers
// they are allowed to import a pipeline. Keyed by path relative to src/ingestion.
const COMPOSITION_ROOTS = new Set(['ingestion-consumer.ts'])
const isCompositionRoot = (absPath) => COMPOSITION_ROOTS.has(path.relative(ING, absPath))

function walk(dir) {
    const out = []
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
            if (SKIP_DIRS.has(entry.name)) {
                continue
            }
            out.push(...walk(path.join(dir, entry.name)))
        } else if (entry.name.endsWith('.ts') && !isTestFile(entry.name)) {
            out.push(path.join(dir, entry.name))
        }
    }
    return out
}

// The ingestion pipeline a path belongs to: a pipeline name, SHARED for other ingestion
// code, or null for non-ingestion / external paths.
function pipelineOf(absPath) {
    const rel = path.relative(ING, absPath)
    if (rel.startsWith('..') || path.isAbsolute(rel)) {
        return null
    }
    const seg = rel.split(path.sep)
    // Pipelines live under `pipelines/<name>/`.
    if (seg[0] === 'pipelines') {
        return seg[1] && PIPELINES.has(seg[1]) ? seg[1] : SHARED
    }
    return PIPELINES.has(seg[0]) ? seg[0] : SHARED
}

// Whether an absolute path lives under src/cdp. Ingestion must reach cdp only through common/.
function isCdp(absPath) {
    const rel = path.relative(CDP, absPath)
    return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))
}

// Whether an absolute path lives under a given root directory.
function isUnder(absPath, root) {
    const rel = path.relative(root, absPath)
    return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel))
}

const IMPORT_PATTERNS = [
    /\bfrom\s*['"]([^'"]+)['"]/g, // import ... from / export ... from
    /\bimport\s*['"]([^'"]+)['"]/g, // side-effect import
    /\bimport\(\s*['"]([^'"]+)['"]\s*\)/g, // dynamic import()
    /\brequire\(\s*['"]([^'"]+)['"]\s*\)/g, // require()
]

function importSpecifiers(source) {
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

// Resolve a specifier to an absolute path, or null for bare/node-module imports.
function resolveSpecifier(spec, importer) {
    if (spec.startsWith('~/tests/')) {
        return path.join(ROOT, 'tests', spec.slice('~/tests/'.length))
    }
    if (spec.startsWith('~/')) {
        return path.join(SRC, spec.slice(2))
    }
    if (spec.startsWith('.')) {
        return path.resolve(path.dirname(importer), spec)
    }
    return null
}

function computeViolations() {
    const violations = new Set()
    for (const file of walk(ING)) {
        const fromPipeline = pipelineOf(file)
        if (fromPipeline === null) {
            continue
        }
        if (isCompositionRoot(file)) {
            continue // composition roots (like the servers) may wire a pipeline
        }
        for (const spec of importSpecifiers(fs.readFileSync(file, 'utf8'))) {
            const target = resolveSpecifier(spec, file)
            if (target === null) {
                continue
            }
            if (isCdp(target)) {
                violations.add(`${path.relative(ROOT, file)} -> cdp`)
                continue
            }
            const toPipeline = pipelineOf(target)
            if (toPipeline === null || toPipeline === SHARED) {
                continue // importing shared code (or leaving ingestion) is always allowed
            }
            if (fromPipeline !== toPipeline) {
                violations.add(`${path.relative(ROOT, file)} -> pipeline:${toPipeline}`)
            }
        }
    }

    // common/ is the shared foundation that both ingestion and cdp build on, so it must not depend
    // on a sibling domain. Guard the ingestion edge: no file under common/ may import ingestion/.
    for (const file of walk(COMMON)) {
        for (const spec of importSpecifiers(fs.readFileSync(file, 'utf8'))) {
            const target = resolveSpecifier(spec, file)
            if (target !== null && isUnder(target, ING)) {
                violations.add(`${path.relative(ROOT, file)} -> ingestion`)
            }
        }
    }

    return [...violations].sort()
}

function main() {
    const current = computeViolations()

    if (process.argv.includes('--write')) {
        fs.writeFileSync(BASELINE, JSON.stringify(current, null, 2) + '\n')
        console.log(`Wrote ${current.length} baselined boundary violation(s) to ${path.relative(ROOT, BASELINE)}`)
        return
    }

    const baseline = fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, 'utf8')) : []
    const baselineSet = new Set(baseline)
    const currentSet = new Set(current)
    const novel = current.filter((v) => !baselineSet.has(v))
    const resolved = baseline.filter((v) => !currentSet.has(v))

    if (resolved.length) {
        console.log(`✓ ${resolved.length} baselined violation(s) resolved — run with --write to shrink the baseline.`)
    }

    if (novel.length) {
        console.error(`\n✗ ${novel.length} new ingestion boundary violation(s):\n`)
        for (const v of novel) {
            console.error(`  ${v}`)
        }
        console.error(
            '\nA pipeline must not import another pipeline, shared ingestion code must not import a pipeline,\n' +
                'no ingestion code may import cdp directly, and no common/ code may import ingestion.'
        )
        console.error('Fix: move the shared dependency into common/ (the cdp∩ingestion meeting point),')
        console.error('or keep the dependency within the importing pipeline.')
        process.exitCode = 1
        return
    }

    console.log(`✓ No new ingestion boundary violations (${current.length} baselined).`)
}

main()
