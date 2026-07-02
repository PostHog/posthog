#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { deltaStatus, formatBytes, formatDelta } from './ci-report/format.mjs'
import { postSection } from './ci-report/update-ci-report.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const frontendDir = path.resolve(__dirname, '..')

// The workflow measures `du -sb frontend/dist` after the PR build and after the base
// build, writing each into these files. They are untracked, so both survive the
// git reset --hard onto the base tree.
function readBytes(name) {
    const file = path.join(frontendDir, name)
    if (!fs.existsSync(file)) {
        return null
    }
    const value = Number.parseInt(fs.readFileSync(file, 'utf-8').trim(), 10)
    return Number.isFinite(value) ? value : null
}

const prBytes = readBytes('dist-size-pr.txt')
if (prBytes === null) {
    console.info('No PR dist size measurement found — nothing to post.')
    process.exit(0)
}
const baseBytes = readBytes('dist-size-base.txt')
if (baseBytes === null) {
    console.warn('No base dist size measurement found — the section will not show a vs-base delta.')
}

// Without a baseline every value looks "new" — a misleading 🔺 delta — so drop the
// comparison and say so, matching the bundle-size section's no-baseline handling.
const body = [
    'Total size of the built `frontend/dist` folder (all assets), compared against the base branch.',
    '',
    baseBytes !== null
        ? `**Total:** ${formatBytes(prBytes)} · ${formatDelta(prBytes, baseBytes)}`
        : `**Total:** ${formatBytes(prBytes)} _(no base branch measurement to compare against yet)_`,
].join('\n')

await postSection({
    id: 'dist-size',
    status: deltaStatus(prBytes - (baseBytes ?? 0), baseBytes !== null),
    summary: baseBytes !== null ? formatDelta(prBytes, baseBytes) : 'no base branch to compare',
    body,
})
