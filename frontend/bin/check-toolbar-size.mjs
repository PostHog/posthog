import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { eagerOutputs, findEntryOutput, jsOutputs, readToolbarMetafile } from './toolbar-metafile.mjs'

// --report-only: write toolbar-size-report.json (the shipped-size numbers) for the shared CI
// comment, exactly like check-eager-graph, without failing the build. build:with-report runs it
// for both the PR and base builds so the comment can show a vs-base delta. The enforcing run
// (no flag) stays a hard-fail CI step.
const reportOnly = process.argv.includes('--report-only')

// Size guards for the split toolbar build (dist/toolbar.js loader + dist/toolbar/ ESM app).
//
// 1. Per-file CloudFront gzip ceiling. CloudFront only compresses responses whose body is
//    between 1,000 and 10,000,000 bytes
//    (https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/ServingCompressedFiles.html).
//    A file that tips over the line is served uncompressed — a ~6x jump on the wire that no
//    size-delta comment makes visible. Code splitting means no single file should ever get
//    close again; if one does, split it rather than raising the limit.
const MAX_FILE_BYTES = 10_000_000

// 2. Eager-set budget: the entry, entry CSS, and everything statically imported from them. This
//    aggregate guardrail catches unexpectedly eager features well before any individual output
//    reaches CloudFront's 10 MB compression cutoff.
const MAX_EAGER_BYTES = 6_000_000

// 3. The loader is injected on every customer page that enables the toolbar and must stay tiny.
const MAX_LOADER_BYTES = 20_000

function humanBytes(bytes) {
    return `${(bytes / 1_000_000).toFixed(2)} MB (${bytes.toLocaleString()} bytes)`
}

let failed = false

function fail(message) {
    console.error(`✗ ${message}`)
    failed = true
}

function statBytes(filePath) {
    try {
        return fs.statSync(path.resolve(process.cwd(), filePath)).size
    } catch {
        fail(`Could not read ${filePath} — build the toolbar before running this check.`)
        return null
    }
}

function main() {
    const metafile = readToolbarMetafile()
    const outputs = metafile.outputs

    // Loader: not in the metafile (separate build), stat it directly.
    const loaderBytes = statBytes('dist/toolbar.js')
    if (loaderBytes !== null && loaderBytes > MAX_LOADER_BYTES) {
        fail(
            `Loader dist/toolbar.js is ${humanBytes(loaderBytes)}, over its ${humanBytes(MAX_LOADER_BYTES)} budget. ` +
                'It ships on every toolbar load before anything runs — app code belongs in the ESM entry.'
        )
    }

    // Per-file ceiling across every shipped artifact (app outputs + loader + copied CSS).
    const shippedFiles = Object.keys(outputs).filter((o) => !o.endsWith('.map'))
    const oversizeFiles = []
    for (const file of [...shippedFiles, 'dist/toolbar.css']) {
        const bytes = outputs[file]?.bytes ?? statBytes(file)
        if (bytes !== null && bytes > MAX_FILE_BYTES) {
            oversizeFiles.push({ file, bytes })
            fail(
                `${file} is ${humanBytes(bytes)}, over the ${humanBytes(MAX_FILE_BYTES)} CloudFront gzip limit — ` +
                    'CloudFront serves files this large uncompressed. Split it further.'
            )
        }
    }

    // CSS completeness: only the entry stylesheet is loaded into the toolbar's shadow root, so
    // styles reachable solely through a lazy chunk would silently never render. Every CSS input
    // that lands in any chunk stylesheet must also land in the entry stylesheet — if this fails,
    // make the owning feature import its styles statically (or hoist the style import).
    // Note: with code splitting, every dynamically-imported module also carries an entryPoint
    // in the metafile — findEntryOutput matches the real toolbar entry specifically.
    const cssIncomplete = []
    const entryCss = outputs[findEntryOutput(outputs)]?.cssBundle
    if (entryCss) {
        const entryCssInputs = new Set(Object.keys(outputs[entryCss].inputs || {}))
        for (const [file, output] of Object.entries(outputs)) {
            if (!file.endsWith('.css') || file.endsWith('.map') || file === entryCss) {
                continue
            }
            const missing = Object.keys(output.inputs || {}).filter((inp) => !entryCssInputs.has(inp))
            if (missing.length) {
                cssIncomplete.push({ file, missing })
                fail(
                    `${file} contains styles missing from the entry stylesheet (${missing.join(', ')}) — ` +
                        'they would never load into the shadow root. Import them statically.'
                )
            }
        }
    }

    // Eager-set budget.
    const eagerJs = [...eagerOutputs(outputs)].filter((o) => o.endsWith('.js'))
    const eagerFiles = entryCss ? [...eagerJs, entryCss] : eagerJs
    const eagerBytes = eagerFiles.reduce((sum, o) => sum + outputs[o].bytes, 0)
    const lazyJs = jsOutputs(outputs).filter((o) => !eagerJs.includes(o))
    const lazyBytes = lazyJs.reduce((sum, o) => sum + outputs[o].bytes, 0)
    if (eagerBytes > MAX_EAGER_BYTES) {
        fail(
            `Eager toolbar output is ${humanBytes(eagerBytes)} across ${eagerFiles.length} files, over the ` +
                `${humanBytes(MAX_EAGER_BYTES)} budget. Something newly reachable through static imports — ` +
                'lazy-load it (import()) or cut the import edge.'
        )
    }

    if (reportOnly) {
        writeReport({
            loaderBytes,
            eagerBytes,
            eagerFiles,
            lazyBytes,
            lazyFiles: lazyJs.length,
            oversizeFiles,
            cssIncomplete,
            outputs,
        })
        // Never fail in report-only mode: the shared CI comment surfaces the numbers and the
        // enforcing run (no flag) is a separate CI step that hard-fails.
        return
    }

    if (failed) {
        process.exit(1)
    }

    console.info(
        `✓ Toolbar sizes OK: loader ${humanBytes(loaderBytes)} (max ${humanBytes(MAX_LOADER_BYTES)}), ` +
            `eager output ${humanBytes(eagerBytes)} in ${eagerFiles.length} files (budget ${humanBytes(MAX_EAGER_BYTES)}), ` +
            `deferred JS ${humanBytes(lazyBytes)} in ${lazyJs.length} files, ` +
            `every file under the ${humanBytes(MAX_FILE_BYTES)} CloudFront gzip limit.`
    )
}

// Written for the shared CI comment (post-toolbar-size-comment.mjs). Mirrors the eager-graph
// report shape: numbers plus the built tree's HEAD sha so the PR build's report is found by sha
// and the plain file (last write = base build) doubles as the vs-base baseline.
function writeReport({
    loaderBytes,
    eagerBytes,
    eagerFiles,
    lazyBytes,
    lazyFiles,
    oversizeFiles,
    cssIncomplete,
    outputs,
}) {
    const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
    const largest = eagerFiles
        .map((o) => ({ file: o, bytes: outputs[o].bytes }))
        .sort((a, b) => b.bytes - a.bytes)
        .slice(0, 10)
    const report = {
        loaderBytes,
        loaderBudget: MAX_LOADER_BYTES,
        loaderOverBudget: loaderBytes !== null && loaderBytes > MAX_LOADER_BYTES,
        eagerBytes,
        eagerFiles: eagerFiles.length,
        budgetBytes: MAX_EAGER_BYTES,
        overBudget: eagerBytes > MAX_EAGER_BYTES,
        lazyBytes,
        lazyFiles,
        maxFileBytes: MAX_FILE_BYTES,
        oversizeFiles,
        cssIncomplete,
        largest,
    }
    try {
        report.sha = execSync('git rev-parse HEAD', { cwd: frontendDir, encoding: 'utf-8' }).trim()
    } catch (err) {
        console.error(`Could not resolve HEAD sha for the toolbar report: ${err.message}`)
    }
    const serialized = JSON.stringify(report, null, 2)
    fs.writeFileSync(path.join(frontendDir, 'toolbar-size-report.json'), serialized)
    if (report.sha) {
        fs.writeFileSync(path.join(frontendDir, `toolbar-size-report-${report.sha}.json`), serialized)
    }
    console.info(
        `Wrote toolbar-size-report.json (eager ${humanBytes(eagerBytes)} / budget ${humanBytes(MAX_EAGER_BYTES)}).`
    )
}

main()
