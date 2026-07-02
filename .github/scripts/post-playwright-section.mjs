#!/usr/bin/env node
import fs from 'node:fs'

import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const reportUrl = process.env.DEPLOYMENT_URL

let failed = []
let flaky = []
let resultsRead = false
try {
    const results = JSON.parse(fs.readFileSync('playwright/results.json', 'utf8'))
    resultsRead = true
    const collect = (suites) => {
        for (const suite of suites || []) {
            for (const spec of suite.specs || []) {
                for (const test of spec.tests || []) {
                    if (test.status === 'unexpected') {
                        failed.push(`- ${spec.title} (${test.projectName})`)
                    } else if (test.status === 'flaky') {
                        flaky.push(`- ${spec.title} (${test.projectName})`)
                    }
                }
            }
            collect(suite.suites)
        }
    }
    collect(results.suites)
} catch {
    // results.json is absent on setup failure/cancellation — handled below.
}

let flakeVerificationLines = ''
try {
    const flakeResults = JSON.parse(fs.readFileSync('playwright/flake-verification-results.json', 'utf8'))
    if (flakeResults.status === 'failed') {
        const fileList = flakeResults.files.map((f) => `- \`${f}\``).join('\n')
        const flakeReportLink = reportUrl ? ` [View report →](${reportUrl})` : ''
        flakeVerificationLines = `\n\n🔁 **Flake verification failed** (--repeat-each=${flakeResults.repeat_count}):\n${fileList}\n\nThe report only shows the tests under verification.${flakeReportLink} Fix these before merging.`
    }
} catch {
    // No flake-verification-results.json — nothing to add.
}

// No results and no flake-verification verdict means the run never got as far as
// testing (setup failure, cancellation) — leave the existing section untouched
// rather than overwrite a previous run's real failures with "all passed".
if (!resultsRead && !flakeVerificationLines) {
    console.info('No Playwright results found — leaving the existing section untouched.')
    process.exit(0)
}

const reportLink = reportUrl ? ` · [View test results →](${reportUrl})` : ''
const footer =
    '\n\n\n*These issues are not necessarily caused by your changes.*\n*Annoyed by this section? Help fix flakies and failures and it will go green!*'

let bodyLines = ''
if (failed.length > 0) {
    bodyLines += `\n\n❌ **${failed.length} failed test${failed.length > 1 ? 's' : ''}:**\n${failed.join('\n')}`
}
if (flaky.length > 0) {
    bodyLines += `\n\n⚠️ **${flaky.length} flaky test${flaky.length > 1 ? 's' : ''}:**\n${flaky.join('\n')}`
}
bodyLines += flakeVerificationLines

const hasProblems = bodyLines.length > 0
const body = hasProblems
    ? `🎭 Playwright report${reportLink}${bodyLines}${footer}`
    : `All tests passed.${reportLink ? `\n\n[View test results →](${reportUrl})` : ''}`

const summaryParts = []
if (failed.length > 0) {
    summaryParts.push(`${failed.length} failed`)
}
if (flaky.length > 0) {
    summaryParts.push(`${flaky.length} flaky`)
}
const summary = summaryParts.length ? summaryParts.join(', ') : 'all passed'

await postSection({
    id: 'playwright',
    status: hasProblems ? 'warn' : 'ok',
    summary,
    body,
})
