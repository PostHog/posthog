#!/usr/bin/env node
// Posts the complexity section of the shared CI report for one language. The
// complexity check is warn-only: this section informs review, it never fails
// the job. Findings JSON comes from `hogli lint:complexity --report` (Python)
// or `bin/lint-complexity.mjs --report` (TypeScript).
//
// Usage: node post-complexity-section.mjs <python|typescript> <findings.json>
import fs from 'node:fs'

import { markdownCell } from '../../frontend/bin/ci-report/format.mjs'
import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_IDS = { python: 'complexity-python', typescript: 'complexity-ts' }

const [language, reportPath] = process.argv.slice(2)
const sectionId = SECTION_IDS[language]
if (!sectionId || !reportPath) {
    console.error('Usage: post-complexity-section.mjs <python|typescript> <findings.json>')
    process.exit(1)
}
if (!fs.existsSync(reportPath)) {
    console.info(`No findings report at ${reportPath} — skipping (branch predates the check?)`)
    process.exit(0)
}

const findings = JSON.parse(fs.readFileSync(reportPath, 'utf8'))
const maxComplexity = findings.reduce((max, finding) => Math.max(max, finding.complexity), 0)
// The limits the linters enforce — quote them instead of hardcoding so a
// limits-only edit cannot leave the report text behind.
const limits = JSON.parse(fs.readFileSync(new URL('../../bin/lint-complexity.limits.json', import.meta.url), 'utf8'))
const summary =
    findings.length > 0
        ? `${findings.length} function${findings.length === 1 ? '' : 's'} above the limit (max ${maxComplexity})`
        : 'clean'

const lines = [
    `Cyclomatic complexity above the limit in changed ${language} files (${limits.production} for production files, ${limits.test} for test files). Warn only: worth simplifying when you next touch these functions.`,
    '',
]
if (findings.length > 0) {
    lines.push('| Function | Location | Complexity | Limit |', '| --- | --- | --- | --- |')
    for (const finding of [...findings].sort((a, b) => b.complexity - a.complexity)) {
        lines.push(
            // `limit` is absent from findings written by linters that predate it.
            `| \`${markdownCell(finding.name)}\` | \`${markdownCell(finding.file)}:${finding.line}\` | ${finding.complexity} | ${finding.limit ?? '?'} |`
        )
    }
}

await postSection({
    id: sectionId,
    status: findings.length > 0 ? 'warn' : 'ok',
    summary,
    body: lines.join('\n'),
})
