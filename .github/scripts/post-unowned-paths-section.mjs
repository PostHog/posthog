#!/usr/bin/env node
// Posts the unowned paths section of the shared CI report. The check is warn-only:
// this section informs review, it never fails the job. The list comes from
// `owners unowned --against <base>`, one path per line.
//
// Usage: node post-unowned-paths-section.mjs <paths.txt>
import fs from 'node:fs'

import { markdownCell } from '../../frontend/bin/ci-report/format.mjs'
import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'unowned-paths'
const SHOWN = 30

const paths = fs.readFileSync(process.argv[2], 'utf8').split('\n').filter(Boolean)

if (paths.length === 0) {
    await clearSectionIfPresent({
        id: SECTION_ID,
        summary: 'no file left without an owner',
        body: 'This pull request leaves no file without an owner.',
    })
} else {
    const lines = [
        'This pull request leaves these files with no owner. Name the owner in the nearest `owners.yaml`, or set `owners: null` for a file that nobody owns on purpose. `hogli owners:who <path>` shows which `owners.yaml` applies. This check only warns.',
        '',
        ...paths.slice(0, SHOWN).map((path) => `- \`${markdownCell(path)}\``),
    ]
    if (paths.length > SHOWN) {
        lines.push(
            `- and ${paths.length - SHOWN} more. Run \`hogli owners:unowned --against origin/master\` for the whole list.`
        )
    }
    await postSection({
        id: SECTION_ID,
        status: 'warn',
        summary: `${paths.length} file${paths.length === 1 ? '' : 's'} with no owner`,
        body: lines.join('\n'),
    })
}
