import fs from 'fs'
import path from 'path'

import { eagerOutputs, jsOutputs, readToolbarMetafile } from './toolbar-metafile.mjs'

// Size guards for the split toolbar build (dist/toolbar.js loader + dist/toolbar/ ESM app).
//
// 1. Per-file CloudFront gzip ceiling. CloudFront only compresses responses whose body is
//    between 1,000 and 10,000,000 bytes
//    (https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/ServingCompressedFiles.html).
//    A file that tips over the line is served uncompressed — a ~6x jump on the wire that no
//    size-delta comment makes visible. Code splitting means no single file should ever get
//    close again; if one does, split it rather than raising the limit.
const MAX_FILE_BYTES = 10_000_000

// 2. Eager-set budget: the entry plus everything statically imported from it — the bytes every
//    toolbar load fetches before any feature runs. Ratchet policy: when a cut lands, lower the
//    budget to lock it in; raise it only as a conscious, reviewed decision in the PR that needs it.
//    2026-07-07: 2,967,721 bytes measured when splitting landed; 2,764,847 after the
//    replay-shared cut; ~10% headroom.
const MAX_EAGER_BYTES = 3_050_000

// 3. The loader is injected on every customer page that enables the toolbar and must stay tiny.
//    2026-07-07: 1,153 bytes minified.
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
    for (const file of [...shippedFiles, 'dist/toolbar.css']) {
        const bytes = outputs[file]?.bytes ?? statBytes(file)
        if (bytes !== null && bytes > MAX_FILE_BYTES) {
            fail(
                `${file} is ${humanBytes(bytes)}, over the ${humanBytes(MAX_FILE_BYTES)} CloudFront gzip limit — ` +
                    'CloudFront serves files this large uncompressed. Split it further.'
            )
        }
    }

    // Eager-set budget.
    const eagerJs = [...eagerOutputs(outputs)].filter((o) => o.endsWith('.js'))
    const eagerBytes = eagerJs.reduce((sum, o) => sum + outputs[o].bytes, 0)
    const lazyJs = jsOutputs(outputs).filter((o) => !eagerJs.includes(o))
    const lazyBytes = lazyJs.reduce((sum, o) => sum + outputs[o].bytes, 0)
    if (eagerBytes > MAX_EAGER_BYTES) {
        fail(
            `Eager toolbar JS is ${humanBytes(eagerBytes)} across ${eagerJs.length} files, over the ` +
                `${humanBytes(MAX_EAGER_BYTES)} budget. Something newly reachable through static imports — ` +
                'lazy-load it (import()) or cut the import edge. See .agents/toolbar-migration.md.'
        )
    }

    if (failed) {
        process.exit(1)
    }

    console.info(
        `✓ Toolbar sizes OK: loader ${humanBytes(loaderBytes)} (max ${humanBytes(MAX_LOADER_BYTES)}), ` +
            `eager JS ${humanBytes(eagerBytes)} in ${eagerJs.length} files (budget ${humanBytes(MAX_EAGER_BYTES)}), ` +
            `deferred JS ${humanBytes(lazyBytes)} in ${lazyJs.length} files, ` +
            `every file under the ${humanBytes(MAX_FILE_BYTES)} CloudFront gzip limit.`
    )
}

main()
