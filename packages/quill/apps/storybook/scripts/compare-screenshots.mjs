#!/usr/bin/env node
/* eslint-disable no-console */
/**
 * Re-run capture against a candidate dir, pixel-diff against baseline, emit a report.
 *
 *   node compare-screenshots.mjs                 # captures into __screenshots__/candidate then diffs
 *   node compare-screenshots.mjs --skip-capture  # only diff existing candidate/ against baseline/
 *
 * Requires: `pnpm add -w pixelmatch pngjs` (or global). Falls back to byte-equal check if unavailable.
 */
import { spawn } from 'node:child_process'
import { createReadStream, existsSync, promises as fs } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')
const BASELINE = resolve(ROOT, '__screenshots__/baseline')
const CANDIDATE = resolve(ROOT, '__screenshots__/candidate')
const REPORT = resolve(ROOT, '__screenshots__/diff-report.json')
const SKIP_CAPTURE = process.argv.includes('--skip-capture')

async function run(cmd, args, env = {}) {
    return new Promise((res, rej) => {
        const p = spawn(cmd, args, { stdio: 'inherit', env: { ...process.env, ...env } })
        p.on('close', (code) => (code === 0 ? res() : rej(new Error(`${cmd} exited ${code}`))))
    })
}

async function captureCandidate() {
    const env = {
        SB_OUT_DIR: CANDIDATE,
    }
    // Temporarily redirect OUT_DIR by setting env the capture script honors. If capture-screenshots
    // doesn't honor SB_OUT_DIR yet, copy the CLI flag approach below.
    await run(process.execPath, [resolve(__dirname, 'capture-screenshots.mjs')], env)
}

async function loadPixelmatch() {
    try {
        const pm = await import('pixelmatch')
        const { PNG } = await import('pngjs')
        return { pixelmatch: pm.default, PNG }
    } catch {
        return null
    }
}

function readPng(PNG, file) {
    return new Promise((res, rej) => {
        createReadStream(file)
            .pipe(new PNG())
            .on('parsed', function () {
                res(this)
            })
            .on('error', rej)
    })
}

async function diffPair(pmLib, a, b) {
    if (!pmLib) {
        // fallback: byte-equal
        const [sa, sb] = await Promise.all([fs.readFile(a), fs.readFile(b)])
        return sa.equals(sb) ? { mismatch: 0, total: sa.length } : { mismatch: -1, total: sa.length }
    }
    const { pixelmatch, PNG } = pmLib
    const [imgA, imgB] = await Promise.all([readPng(PNG, a), readPng(PNG, b)])
    if (imgA.width !== imgB.width || imgA.height !== imgB.height) {
        return { mismatch: -1, total: imgA.width * imgA.height, reason: 'size-mismatch' }
    }
    const out = new PNG({ width: imgA.width, height: imgA.height })
    const diff = pixelmatch(imgA.data, imgB.data, out.data, imgA.width, imgA.height, { threshold: 0.1 })
    return { mismatch: diff, total: imgA.width * imgA.height }
}

async function main() {
    if (!SKIP_CAPTURE) {
        await captureCandidate()
    }
    if (!existsSync(CANDIDATE)) {
        throw new Error(`Candidate dir missing: ${CANDIDATE}`)
    }
    const pmLib = await loadPixelmatch()
    if (!pmLib) {
        console.warn('pixelmatch not installed — falling back to byte-equal check')
    }

    const baseline = JSON.parse(await fs.readFile(resolve(BASELINE, 'manifest.json'), 'utf8'))
    const results = []
    for (const [id, story] of Object.entries(baseline.stories)) {
        for (const theme of Object.keys(story.screenshots)) {
            const b = resolve(BASELINE, theme, `${id}.png`)
            const c = resolve(CANDIDATE, theme, `${id}.png`)
            if (!existsSync(c)) {
                results.push({ id, theme, status: 'missing' })
                continue
            }
            const { mismatch, total, reason } = await diffPair(pmLib, b, c)
            results.push({
                id,
                theme,
                status: mismatch === 0 ? 'pass' : 'diff',
                mismatch,
                total,
                reason,
            })
        }
    }

    const passes = results.filter((r) => r.status === 'pass').length
    const diffs = results.filter((r) => r.status === 'diff')
    const missing = results.filter((r) => r.status === 'missing')
    const report = { when: new Date().toISOString(), passes, diffs: diffs.length, missing: missing.length, results }
    await fs.writeFile(REPORT, JSON.stringify(report, null, 2))
    console.log(`\nDiff summary: pass=${passes} diff=${diffs.length} missing=${missing.length}`)
    if (diffs.length) {
        console.log('Top 20 regressions:')
        diffs
            .sort((a, b) => (b.mismatch ?? 0) - (a.mismatch ?? 0))
            .slice(0, 20)
            .forEach((r) => console.log(` - ${r.theme} ${r.id}: ${r.mismatch}/${r.total} (${r.reason || 'px-diff'})`))
    }
    if (diffs.length || missing.length) {
        process.exit(1)
    }
}

main().catch((e) => {
    console.error(e)
    process.exit(1)
})
