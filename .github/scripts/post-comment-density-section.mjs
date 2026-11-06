#!/usr/bin/env node
import { pathToFileURL } from 'node:url'

import {
    clearSectionIfPresent,
    isReportComment,
    listPrComments,
    parseSections,
    postSection,
    resolvePrContext,
} from '../../frontend/bin/ci-report/update-ci-report.mjs'

const SECTION_ID = 'comment-density'

// A push whose diff could not be fetched must not leave the previous push's
// warning standing as if it described this one.
async function markUnmeasured() {
    const context = resolvePrContext(`marking "${SECTION_ID}" unmeasured`)
    if (!context) {
        return
    }
    const reportComment = (await listPrComments(context)).find(isReportComment)
    if (!reportComment || !parseSections(reportComment.body).has(SECTION_ID)) {
        return
    }
    await postSection({
        id: SECTION_ID,
        status: 'info',
        summary: 'not measured on this push',
        body: 'The PR diff could not be fetched for this push (usually because it is too large for the API), so the comment share was not measured. The previous result no longer applies.',
    })
}

async function main() {
    const { AVAILABLE, STATUS, SUMMARY, BODY } = process.env
    if (AVAILABLE !== 'true') {
        await markUnmeasured()
        return
    }
    if (STATUS === 'warn' || STATUS === 'alert') {
        await postSection({ id: SECTION_ID, status: STATUS, summary: SUMMARY, body: BODY })
        return
    }
    await clearSectionIfPresent({ id: SECTION_ID, summary: SUMMARY, body: BODY })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    await main()
}
