#!/usr/bin/env node
// Posts the typing section of the shared CI report. check_touched_typing.py writes the
// section into its report, so the wording lives in one place.
//
// Usage: node post-touched-typing-section.mjs <report.json>
import fs from 'node:fs'

import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'touched-typing'

const [reportPath] = process.argv.slice(2)
if (!reportPath || !fs.existsSync(reportPath)) {
    console.info(`No report at ${reportPath} — skipping (branch predates the check?)`)
    process.exit(0)
}

const { section } = JSON.parse(fs.readFileSync(reportPath, 'utf8'))
if (section) {
    await postSection({ id: SECTION_ID, ...section })
} else {
    await clearSectionIfPresent({
        id: SECTION_ID,
        summary: 'clean',
        body: 'Every function this PR touches is fully annotated.',
    })
}
