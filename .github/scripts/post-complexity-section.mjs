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
const summary =
    findings.length > 0
        ? `${findings.length} function${findings.length === 1 ? '' : 's'} above 10 (max ${maxComplexity})`
        : 'clean'

const lines = [
    `Cyclomatic complexity above 10 in changed ${language} files. Warn only: worth simplifying when you next touch these functions.`,
    '',
]
if (findings.length > 0) {
    lines.push('| Function | Location | Complexity |', '| --- | --- | --- |')
    for (const finding of [...findings].sort((a, b) => b.complexity - a.complexity)) {
        lines.push(
            `| \`${markdownCell(finding.name)}\` | \`${markdownCell(finding.file)}:${finding.line}\` | ${finding.complexity} |`
        )
    }
}

await postSection({
    id: sectionId,
    status: findings.length > 0 ? 'warn' : 'ok',
    summary,
    body: lines.join('\n'),
})
