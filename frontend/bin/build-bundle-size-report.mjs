#!/usr/bin/env node
import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')
const reportDir = path.join(frontendDir, 'dist-report')

// Mirrors the compressed-size-action config this replaces (ci-frontend.yml):
//   pattern: frontend/dist-report/**/*.js   exclude: {**/_chunks/chunk*.js}
//   compression: none                       strip-hash: -[A-Za-z0-9]{8}\.js$
// dist-report/ (built by build-bundle-report.mjs) carries the source bundle and source
// path in each filename, so a stripped hash yields a stable identity across builds.
const HASH_SUFFIX = /-[A-Za-z0-9]{8}(\.js)$/
const CHUNK_EXCLUDE = /(^|\/)_chunks\/chunk[^/]*\.js$/

function walk(dir) {
    const out = []
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name)
        if (entry.isDirectory()) {
            out.push(...walk(full))
        } else if (entry.isFile() && entry.name.endsWith('.js')) {
            out.push(full)
        }
    }
    return out
}

if (!fs.existsSync(reportDir)) {
    console.error(
        `Bundle size report: ${reportDir} not found — run build-bundle-report.mjs first (build:with-report does).`
    )
    process.exit(1)
}

const files = []
for (const full of walk(reportDir)) {
    const identity = path.relative(reportDir, full).split(path.sep).join('/').replace(HASH_SUFFIX, '$1')
    if (CHUNK_EXCLUDE.test(identity)) {
        continue
    }
    files.push({ file: identity, bytes: fs.statSync(full).size })
}
files.sort((a, b) => a.file.localeCompare(b.file))

const report = { files, total: files.reduce((sum, f) => sum + f.bytes, 0) }

// The sha convention matches eager-graph-report: compressed-size-action's replacement
// builds the PR branch AND the base branch in the same workspace, so the plain filename
// holds the LAST build's numbers (the base's) and doubles as the vs-base baseline, while
// the sha-suffixed file identifies the PR build's own report.
try {
    report.sha = execSync('git rev-parse HEAD', { cwd: frontendDir, encoding: 'utf-8' }).trim()
} catch (err) {
    console.error(`Could not resolve HEAD sha for the bundle size report: ${err.message}`)
}

const serialized = JSON.stringify(report, null, 2)
fs.writeFileSync(path.join(frontendDir, 'bundle-size-report.json'), serialized)
if (report.sha) {
    fs.writeFileSync(path.join(frontendDir, `bundle-size-report-${report.sha}.json`), serialized)
}

console.info(`Bundle size report: ${files.length} files, ${(report.total / 1024 / 1024).toFixed(2)} MiB total`)
