#!/usr/bin/env node
// Posts the backend patch-coverage section to the shared CI report comment. Usage:
//   node post-coverage-section.mjs <coverage-comment.md path> <patch-coverage.json path>
// The `backend-coverage` section id must be registered in SECTIONS in update-ci-report.mjs.
//
import fs from 'node:fs'

import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const [bodyPath, patchJsonPath] = process.argv.slice(2)
if (!bodyPath || !patchJsonPath) {
    console.error('Usage: post-coverage-section.mjs <coverage-comment.md path> <patch-coverage.json path>')
    process.exit(1)
}

// An undetermined patch (diff-cover unavailable, or no coverage ran) must not clear a
// real warning from an earlier complete run — leave the section untouched.
let patch
try {
    patch = JSON.parse(fs.readFileSync(patchJsonPath, 'utf8'))
} catch {
    console.info('Patch coverage undetermined — leaving any existing section untouched.')
    process.exit(0)
}

const body = fs.readFileSync(bodyPath, 'utf8').trim()
const totalLines = Number(patch.total_num_lines) || 0
const violations = Number(patch.total_num_violations) || 0
const pct = Number(patch.total_percent_covered) || 0

if (totalLines === 0) {
    await clearSectionIfPresent({
        id: 'backend-coverage',
        summary: 'no measured backend lines changed',
        body,
    })
    process.exit(0)
}

if (violations > 0) {
    await postSection({
        id: 'backend-coverage',
        status: 'warn',
        summary: `${pct.toFixed(1)}% of changed backend lines covered — ${violations} uncovered`,
        body,
    })
    process.exit(0)
}

await clearSectionIfPresent({
    id: 'backend-coverage',
    summary: 'all changed backend lines covered',
    body,
})
