#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { markdownCell } from '../../frontend/bin/ci-report/format.mjs'
import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const MAX_ROWS = 50
const NEEDS_A_LOOK = new Set(['high_risk', 'not_scanned'])
const INTRO =
    'GuardDog scans each registry package this pull request adds to a lockfile or a go.mod file. This check is advisory and does not block the merge. Most findings are false positives, so read the rule names before acting.'

function count(number, noun) {
    return `${number} ${noun}${number === 1 ? '' : 's'}`
}

export function buildDependencyScanSection({ scanned, skipped, flagged }) {
    const needsALook = flagged.filter((finding) => NEEDS_A_LOOK.has(finding.label))
    const highRisk = flagged.filter((finding) => finding.label === 'high_risk').length
    const notScanned = flagged.filter((finding) => finding.label === 'not_scanned').length + skipped
    const summaryParts = []
    if (highRisk > 0) {
        summaryParts.push(count(highRisk, 'high-risk package'))
    }
    if (notScanned > 0) {
        summaryParts.push(`${count(notScanned, 'package')} not scanned`)
    }
    const lines = [INTRO, '', `Scanned ${count(scanned, 'package')}.`]
    if (skipped > 0) {
        lines.push(
            '',
            `${count(skipped, 'package')} could not be scanned because ${skipped === 1 ? 'it is' : 'they are'} not a plain registry release or the pull request adds too many packages.`
        )
    }
    if (flagged.length > 0) {
        lines.push('', '| Package | Ecosystem | Label | Score | Rules |', '| --- | --- | --- | --- | --- |')
        for (const finding of flagged.slice(0, MAX_ROWS)) {
            lines.push(
                `| \`${markdownCell(finding.package)}\` | ${markdownCell(finding.ecosystem)} | ${markdownCell(finding.label)} | ${Number(finding.score).toFixed(1)} | ${markdownCell(finding.rules.join(', '))} |`
            )
        }
        if (flagged.length > MAX_ROWS) {
            lines.push('', `${flagged.length - MAX_ROWS} more flagged packages are in the job summary.`)
        }
    }
    return {
        status: needsALook.length > 0 || skipped > 0 ? 'warn' : 'ok',
        summary: summaryParts.length > 0 ? summaryParts.join(', ') : `clean, ${count(scanned, 'package')} scanned`,
        body: lines.join('\n'),
    }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    const findings = JSON.parse(process.env.FINDINGS || 'null')
    if (!findings) {
        console.info('No findings from the scan job, so there is nothing to post.')
        process.exit(0)
    }
    await postSection({ id: 'dependency-scan', ...buildDependencyScanSection(findings) })
}
