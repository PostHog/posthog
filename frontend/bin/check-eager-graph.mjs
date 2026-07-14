#!/usr/bin/env node
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const metaPath = path.join(frontendDir, 'posthog-app-esbuild-meta.json')

// --report-only: record results without failing the build. Used by build:with-report
// because the CI bundle-size job runs that script for BOTH the PR build and the base
// build — a base-branch budget breach must not abort the job for every open PR.
// Budget breaches are surfaced as warnings in the dedicated workflow step via --assert-report.
const reportOnly = process.argv.includes('--report-only')

// --assert-report <path>: skip measuring; read a previously written report and surface any
// recorded violations as warnings (GitHub Actions annotations) without failing CI — the
// bundle-size Signals scout tracks regressions from the PR comment, so the check informs.
const assertReportIndex = process.argv.indexOf('--assert-report')

// The eager graph is everything a root actually SHIPS on the critical path — the bytes a
// browser downloads and parses before that surface is interactive. It is measured from the
// esbuild OUTPUT chunks: the root's entry chunk plus every chunk reachable through static
// (import-statement) chunk edges, plus each visited chunk's attached stylesheet (cssBundle,
// which is downloaded before render). Lazy (dynamic-import) chunks are excluded, and tree-shaken
// code is already gone from the output — so a side-effect-free re-export barrel only costs
// what its used exports actually ship, not its whole surface (the earlier input-graph metric
// counted the whole barrel and mistook reachability for shipped weight).
// Total dist size can't see this regression class (a fake-lazy import moves no total bytes
// but shifts them onto the eager path), which is why this check exists.
//
// Budgets are eager output bytes (shipped JS + eager CSS, minified).
// Ratchet policy: when a bundle-splitting win lands, lower the budget to lock it in;
// raise a budget only as a conscious, reviewed decision in the PR that needs it.
const ROOTS = [
    {
        root: 'src/index.tsx',
        label: 'entry (logged-out pages, app bootstrap)',
        // 2026-07-01: 3.75 MiB eager output (2.73 MiB JS + 1.02 MiB eager CSS, 21 chunks).
        // ~15% headroom so routine churn doesn't trip the warn; ratchet down on a split win.
        budgetBytes: 4_500_000,
        forbidden: [
            'node_modules/monaco-editor/',
            'src/lib/components/ActivityLog/describers',
            // Inlined hoggie SVGs are huge (up to ~1 MiB each), and one static barrel import
            // from eager code drags every hoggie used anywhere in the app onto the eager
            // path. All app code uses pngHoggie (lib/brand/hoggies) instead - the package's
            // `hoggies/png/*` URL stubs are allowed (a few bytes each, the image bytes stay
            // out of the JS bundle entirely). Nothing imports the SVG modules today (oxlint
            // no-restricted-imports bans them), so these are tripwires: verifyPrefix checks
            // the package is still laid out as expected via the PNG stubs that DO ship.
            {
                pattern: 'node_modules/@posthog/brand/dist/generated/hoggies/svg/',
                verifyPrefix: 'node_modules/@posthog/brand/dist/generated/hoggies/',
            },
            {
                pattern: 'node_modules/@posthog/brand/dist/generated/hoggies/components/',
                verifyPrefix: 'node_modules/@posthog/brand/dist/generated/hoggies/',
            },
        ],
    },
    {
        root: 'src/scenes/AuthenticatedShell.tsx',
        label: 'authenticated shell (every logged-in page)',
        // 2026-07-07: 8.02 MiB eager output after moving all @posthog/brand/hoggies usage in
        // eager code to PNG stubs (lib/brand/hoggies) — the inline-SVG modules are now a
        // forbidden module below. ~15% headroom so routine churn doesn't trip the warn.
        budgetBytes: 9_700_000,
        forbidden: [
            'node_modules/monaco-editor/',
            'src/lib/components/ActivityLog/describers',
            // See the entry root's note: inline-SVG hoggies must stay off the eager path.
            {
                pattern: 'node_modules/@posthog/brand/dist/generated/hoggies/svg/',
                verifyPrefix: 'node_modules/@posthog/brand/dist/generated/hoggies/',
            },
            {
                pattern: 'node_modules/@posthog/brand/dist/generated/hoggies/components/',
                verifyPrefix: 'node_modules/@posthog/brand/dist/generated/hoggies/',
            },
        ],
    },
]

function fail(message) {
    console.error(`\n❌ ${message}`)
    process.exitCode = 1
}

function warnViolation(message) {
    console.warn(`\n⚠️ ${message}`)
    const encoded = message.replace(/%/g, '%25').replace(/\r/g, '%0D').replace(/\n/g, '%0A')
    // console.info (not console.log, which oxlint strips) writes to stdout, where GitHub Actions parses workflow commands.
    console.info(`::warning title=Eager graph budget::${encoded}`)
}

function assertReport(reportFilePath) {
    if (!fs.existsSync(reportFilePath)) {
        warnViolation(`Report not found at ${reportFilePath} — did the build run the check?`)
        return 1
    }
    const reportToAssert = JSON.parse(fs.readFileSync(reportFilePath, 'utf-8'))
    let violations = 0
    for (const message of reportToAssert.warnings ?? []) {
        warnViolation(message)
    }
    const topLevelErrors = reportToAssert.errors ?? []
    for (const message of topLevelErrors) {
        warnViolation(message)
        violations++
    }
    for (const r of reportToAssert.roots) {
        if (r.overBudget) {
            warnViolation(
                `Eager graph for '${r.root}' ships ${formatMiB(r.bytes)}, over the ${formatMiB(r.budgetBytes)} budget.\n` +
                    `Largest eagerly-shipped files:\n` +
                    r.largest.map(({ file, bytes }) => `   ${formatMiB(bytes).padStart(9)}  ${file}`).join('\n') +
                    `\nMake the offending import lazy (React.lazy / dynamic import()), or raise the budget in ` +
                    `frontend/bin/check-eager-graph.mjs as a conscious decision in this PR.`
            )
            violations++
        }
        for (const hit of r.forbiddenHits) {
            warnViolation(
                `'${hit.module}' ships eagerly from '${r.root}' — it must stay behind a dynamic import.\n` +
                    `Import chain:\n   ${hit.chain.join('\n   -> ')}`
            )
            violations++
        }
        if (topLevelErrors.length === 0 && !r.overBudget && r.forbiddenHits.length === 0) {
            console.info(`🟢 ${r.label}: ${formatMiB(r.bytes)} within ${formatMiB(r.budgetBytes)}`)
        }
    }
    return violations
}

if (assertReportIndex !== -1) {
    const violations = assertReport(process.argv[assertReportIndex + 1])
    if (violations) {
        console.warn(
            `\n⚠️ Eager graph check — ${violations} issue(s) above. Not failing CI: the bundle-size ` +
                `Signals scout tracks eager-graph regressions from the PR comment. Trim the eager closure when you can.`
        )
    } else {
        // Neutral wording: warnings (e.g. a stale forbidden pattern) may have printed above
        // without counting as violations, so don't declare an unqualified all-clear.
        console.info('\nNo eager graph budget violations.')
    }
    process.exit(0)
}

function formatMiB(bytes) {
    return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
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

const meta = JSON.parse(fs.readFileSync(metaPath, 'utf-8'))
const inputs = meta.inputs
const outputs = meta.outputs
if (!outputs) {
    fail(`Metafile at ${metaPath} has no "outputs" — rebuild with metafile output enabled.`)
    process.exit(1)
}

// esbuild makes every code-split point (real entry points and dynamically-imported
// modules alike) an entryPoint of some output chunk, so a root maps to exactly one chunk.
function entryChunk(root) {
    for (const [name, chunk] of Object.entries(outputs)) {
        if (chunk.entryPoint === root) {
            return name
        }
    }
    return null
}

// The eager download for a root: its entry chunk plus every chunk reachable through static
// (import-statement) chunk edges. dynamic-import edges are the lazy boundaries — stop there.
function eagerChunkClosure(entry) {
    const seen = new Set([entry])
    const queue = [entry]
    while (queue.length) {
        const chunk = queue.shift()
        for (const imp of outputs[chunk].imports || []) {
            if (imp.kind !== 'import-statement' || seen.has(imp.path) || !outputs[imp.path]) {
                continue
            }
            seen.add(imp.path)
            queue.push(imp.path)
        }
    }
    return seen
}

const summaryLines = ['## Eager graph check', '', '| Root | Eager size | Budget | Files |', '| --- | --- | --- | --- |']
const report = { roots: [], errors: [], warnings: [] }

// Computed once: the full set of module paths known to this build. Shared across all roots
// because `inputs` is the global metafile index, not per-root.
const allInputKeys = Object.keys(inputs)

// Forbidden entries are strings, or { pattern, verifyPrefix } when the pattern is a pure
// tripwire that legitimately matches nothing in a healthy build.
const forbiddenPattern = (entry) => (typeof entry === 'string' ? entry : entry.pattern)
const forbiddenVerify = (entry) => (typeof entry === 'string' ? entry : entry.verifyPrefix)

// Self-verify: each forbidden pattern's verify prefix should match at least one module present
// anywhere in the metafile inputs. If it matches nothing, the path string is stale (dist layout
// changed, package renamed) and the guard silently stops enforcing. Tripwire entries verify a
// broader prefix instead, since matching nothing is their healthy state. Warn once per unique
// prefix so a pattern shared across roots doesn't produce duplicate annotations.
for (const verifySubstr of new Set(ROOTS.flatMap((r) => r.forbidden.map(forbiddenVerify)))) {
    if (!allInputKeys.some((f) => f.includes(verifySubstr))) {
        const msg =
            `Forbidden pattern (or its verify prefix) '${verifySubstr}' does not match any module in the build — ` +
            `the path may be stale. Update it in frontend/bin/check-eager-graph.mjs.`
        warnViolation(msg)
        report.warnings.push(msg)
    }
}

for (const { root, label, budgetBytes, forbidden } of ROOTS) {
    const entry = entryChunk(root)
    if (!entry) {
        const candidates = Object.values(outputs)
            .map((c) => c.entryPoint)
            .filter((e) => e && e.endsWith(path.basename(root)))
            .slice(0, 5)
        const message = `Root '${root}' is not an entry chunk in the metafile. Was it moved, or is it no longer a code-split boundary? Candidates: ${candidates.join(', ')}`
        report.errors.push(message)
        fail(message)
        continue
    }

    // Attribute each input module the bytes it actually contributes to the eager chunks —
    // tree-shaken modules contribute nothing, so a barrel only counts its used exports.
    const eagerBytesByFile = new Map()
    const cssBundlesSeen = new Set()
    let totalBytes = 0
    for (const chunk of eagerChunkClosure(entry)) {
        totalBytes += outputs[chunk].bytes
        // esbuild attaches a JS chunk's stylesheet via `cssBundle`, not an `imports` edge, so
        // the chunk walk never reaches it — but it's downloaded before render, so count each
        // distinct eager stylesheet once. Without this, adding a large eager .scss moves real
        // bytes onto the critical path while the metric stays flat.
        const cssBundle = outputs[chunk].cssBundle
        if (cssBundle && !cssBundlesSeen.has(cssBundle)) {
            cssBundlesSeen.add(cssBundle)
            totalBytes += outputs[cssBundle]?.bytes || 0
        }
        for (const [file, info] of Object.entries(outputs[chunk].inputs || {})) {
            if (info.bytesInOutput > 0) {
                eagerBytesByFile.set(file, (eagerBytesByFile.get(file) || 0) + info.bytesInOutput)
            }
        }
    }
    const largest = [...eagerBytesByFile.entries()].sort((a, b) => b[1] - a[1]).slice(0, 15)

    const overBudget = totalBytes > budgetBytes

    // A forbidden module is a hit when it ships in the eager OUTPUT. The import chain we show
    // is a best-effort trace through the INPUT graph — module-level `import` edges are what a
    // human reads — computed once per root, only when there is a hit. The two graphs can
    // diverge (a module can ship eagerly via a bundler-injected or re-export edge with no
    // source-level import path), so the chain is a pointer, not the byte source, and may be
    // short when the output edge has no input-graph counterpart.

    const hitFiles = new Map()
    for (const forbiddenSubstr of forbidden.map(forbiddenPattern)) {
        const hit = [...eagerBytesByFile.keys()].find((f) => f.includes(forbiddenSubstr))
        if (hit) {
            hitFiles.set(forbiddenSubstr, hit)
        }
    }
    const forbiddenHits = []
    if (hitFiles.size > 0) {
        const { parentOf } = eagerClosure(inputs, root)
        for (const [module, hit] of hitFiles) {
            forbiddenHits.push({ module, chain: chainTo(parentOf, hit) })
        }
    }

    const status = overBudget || forbiddenHits.length > 0 ? '🟡' : '🟢'
    console.info(`${status} ${label}`)
    console.info(`   root: ${root}`)
    console.info(
        `   eager output: ${eagerBytesByFile.size} files, ${formatMiB(totalBytes)} (budget ${formatMiB(budgetBytes)})`
    )
    summaryLines.push(
        `| ${status} \`${root}\` | ${formatMiB(totalBytes)} | ${formatMiB(budgetBytes)} | ${eagerBytesByFile.size} |`
    )

    if (overBudget) {
        fail(
            `Eager graph for '${root}' ships ${formatMiB(totalBytes)}, over the ${formatMiB(budgetBytes)} budget.\n` +
                `Something newly shipped on the eager path is inflating it. Largest eagerly-shipped files:\n` +
                largest.map(([f, b]) => `   ${formatMiB(b).padStart(10)}  ${f}`).join('\n') +
                `\nMake the offending import lazy (React.lazy / dynamic import()), or raise the budget in ` +
                `frontend/bin/check-eager-graph.mjs as a conscious decision in this PR.`
        )
    }

    for (const hit of forbiddenHits) {
        fail(
            `'${hit.module}' ships eagerly from '${root}' — it must stay behind a dynamic import.\n` +
                `Import chain:\n   ${hit.chain.join('\n   -> ')}`
        )
    }

    report.roots.push({
        root,
        label,
        bytes: totalBytes,
        files: eagerBytesByFile.size,
        budgetBytes,
        overBudget,
        forbidden,
        forbiddenHits,
        largest: largest.map(([f, b]) => ({ file: f, bytes: b })),
    })
}

// Consumed by the workflow's comment + enforcement steps; written even on failure so
// the PR comment can show what went over. The filename and the embedded sha carry the
// built tree's HEAD because the CI bundle-size job runs this for BOTH the PR build and
// the base build in the same workspace — the PR build's report is found by sha, and the
// plain filename (last write = the base build) doubles as the base-branch measurement
// for the comment's vs-base delta.
try {
    report.sha = execSync('git rev-parse HEAD', { cwd: frontendDir, encoding: 'utf-8' }).trim()
} catch (err) {
    console.error(`Could not resolve HEAD sha for the report: ${err.message}`)
}
const serialized = JSON.stringify(report, null, 2)
fs.writeFileSync(path.join(frontendDir, 'eager-graph-report.json'), serialized)
if (report.sha) {
    fs.writeFileSync(path.join(frontendDir, `eager-graph-report-${report.sha}.json`), serialized)
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
