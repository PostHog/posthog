#!/usr/bin/env node
import fse from 'fs-extra'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const reportDir = path.join(frontendDir, 'dist-report')

const META_SUFFIX = '-esbuild-meta.json'

// entryPoint can be `../products/...` for workspace imports — flatten `..` so the
// destination stays under the per-bundle subdir of dist-report/.
// The CI bundle-size action's `**/_chunks/chunk*.js` exclude (in
// .github/workflows/ci-frontend.yml) depends on the `_chunks` literal below;
// keep them in sync if either changes.
function sanitizeSourcePath(p) {
    return p
        .split(path.sep)
        .map((s) => (s === '..' ? '_parent' : s))
        .join(path.sep)
}

function discoverMetafiles() {
    return fse
        .readdirSync(frontendDir)
        .filter((name) => name.endsWith(META_SUFFIX))
        .map((name) => ({
            name: name.slice(0, -META_SUFFIX.length),
            metaPath: path.join(frontendDir, name),
        }))
        .sort((a, b) => a.name.localeCompare(b.name))
}

fse.removeSync(reportDir)
fse.mkdirSync(reportDir, { recursive: true })

const metafiles = discoverMetafiles()
if (metafiles.length === 0) {
    console.error(
        `Bundle report: no ${META_SUFFIX} files found in ${frontendDir}. ` +
            `Each production esbuild config must have writeMetaFile enabled — see frontend/build.mjs. ` +
            `Did the esbuild step run?`
    )
    process.exit(1)
}

let totalCopied = 0
for (const { name, metaPath } of metafiles) {
    let meta
    try {
        meta = JSON.parse(fse.readFileSync(metaPath, 'utf-8'))
    } catch (err) {
        console.error(`Bundle report: failed to parse ${metaPath}: ${err.message}`)
        process.exit(1)
    }

    let copiedForBundle = 0
    for (const [outPath, outInfo] of Object.entries(meta.outputs)) {
        if (!outPath.endsWith('.js')) {
            continue
        }
        const src = path.resolve(frontendDir, outPath)
        if (!fse.existsSync(src)) {
            console.warn(`Bundle report: ${name} metafile lists ${outPath} but file is missing on disk; skipping`)
            continue
        }

        const baseFile = path.basename(outPath)
        const subPath =
            outInfo.entryPoint && outInfo.entryPoint !== '.'
                ? path.join(sanitizeSourcePath(path.dirname(outInfo.entryPoint)), baseFile)
                : path.join('_chunks', baseFile)

        const dest = path.join(reportDir, name, subPath)
        fse.mkdirSync(path.dirname(dest), { recursive: true })
        fse.copyFileSync(src, dest)
        copiedForBundle++
        totalCopied++
    }

    if (copiedForBundle === 0) {
        console.error(`Bundle report: bundle "${name}" contributed zero .js outputs; metafile may be stale`)
        process.exit(1)
    }
}

console.info(
    `Bundle report: wrote ${totalCopied} files from ${metafiles.length} bundle(s) (${metafiles
        .map((m) => m.name)
        .join(', ')}) to ${reportDir}`
)
