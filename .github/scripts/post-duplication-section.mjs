#!/usr/bin/env node
// Posts the duplication section of the shared CI report for one language. The
// duplication check is advisory while the gate proves itself: this section
// informs review, it never fails the job. Findings JSON comes from
// `python3 bin/lint_duplication.py --report-dir .`.
//
// Usage: node post-duplication-section.mjs <python|typescript> <findings.json>
import fs from 'node:fs'

import { markdownCell } from '../../frontend/bin/ci-report/format.mjs'
import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_IDS = { python: 'duplication-python', typescript: 'duplication-ts' }
const LANGUAGE_NAMES = { python: 'Python', typescript: 'TypeScript' }

const [language, reportPath] = process.argv.slice(2)
const sectionId = SECTION_IDS[language]
if (!sectionId || !reportPath) {
    console.error('Usage: post-duplication-section.mjs <python|typescript> <findings.json>')
    process.exit(1)
}
const statusPath = reportPath.replace(/duplication-findings-[^/]+\.json$/, 'duplication-scan-status.json')
// The lint writes this before the scans start, so a failed scan is
// distinguishable from an unrebased branch (which has no files at all).
// Check it first: a failed scan must replace any stale section from an
// earlier commit rather than leave it standing.
if (fs.existsSync(statusPath) && JSON.parse(fs.readFileSync(statusPath, 'utf8')).status === 'failed') {
    await postSection({
        id: sectionId,
        status: 'fail',
        summary: 'the duplication scan could not run',
        body: 'The duplication scan failed on this run (see the job log). Nothing here says whether this branch adds duplication.',
    })
    process.exit(0)
}
if (!fs.existsSync(reportPath)) {
    console.info(`No findings report at ${reportPath} — skipping (branch predates the check?)`)
    process.exit(0)
}

const findings = JSON.parse(fs.readFileSync(reportPath, 'utf8'))
const worst = findings.reduce((max, finding) => Math.max(max, finding.tokens), 0)
// The limits the linter enforces — quote them instead of hardcoding so a
// limits-only edit cannot leave the report text behind.
const limits = JSON.parse(fs.readFileSync(new URL('../../bin/lint-duplication.limits.json', import.meta.url), 'utf8'))
const summary =
    findings.length > 0
        ? `${findings.length} new duplicated block${findings.length === 1 ? '' : 's'} (worst ${worst} tokens)`
        : 'clean'

const lines = [
    `New ${LANGUAGE_NAMES[language]} code duplication introduced by this branch. Fails at ${limits.production}+ tokens in app code, or ${limits.test}+ tokens when both copies live in test files. Advisory while the gate proves itself: extract a shared helper instead of copying.`,
    '',
]
if (findings.length > 0) {
    lines.push('| First copy | Second copy | Lines | Tokens |', '| --- | --- | --- | --- |')
    for (const finding of findings) {
        lines.push(
            `| \`${markdownCell(finding.first_file)}:${finding.first_start}\` | \`${markdownCell(finding.second_file)}:${finding.second_start}\` | ${finding.lines} | ${finding.tokens} |`
        )
    }
}

await postSection({
    id: sectionId,
    status: findings.length > 0 ? 'warn' : 'ok',
    summary,
    body: lines.join('\n'),
})
