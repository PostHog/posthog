#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'comment-density'

async function main() {
    const { STATUS, SUMMARY, BODY } = process.env
    if (STATUS === 'warn' || STATUS === 'alert') {
        await postSection({ id: SECTION_ID, status: STATUS, summary: SUMMARY, body: BODY })
        return
    }
    await clearSectionIfPresent({ id: SECTION_ID, summary: SUMMARY, body: BODY })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
