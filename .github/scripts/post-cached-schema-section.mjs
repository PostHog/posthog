#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'cached-schema-removals'

async function main() {
    const { REMOVED, STATUS, SUMMARY, BODY } = process.env
    if (REMOVED === 'true') {
        await postSection({ id: SECTION_ID, status: STATUS, summary: SUMMARY, body: BODY })
        return
    }
    await clearSectionIfPresent({
        id: SECTION_ID,
        summary: 'no removed fields',
        body: 'No fields were removed from the models that cached query responses store.',
    })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
