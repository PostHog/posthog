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

// A push whose diff could not be fetched must not leave the previous push's
// warning standing as if it described this one.
async function markUnmeasured(sectionId) {
    const context = resolvePrContext(`marking "${sectionId}" unmeasured`)
    if (!context) {
        return
    }
    const reportComment = (await listPrComments(context)).find(isReportComment)
    if (!reportComment || !parseSections(reportComment.body).has(sectionId)) {
        return
    }
    await postSection({
        id: sectionId,
        status: 'info',
        summary: 'not measured on this push',
        body: 'This check could not run on this push, usually because the PR diff is too large for the API to return. The previous result no longer applies.',
    })
}

async function main() {
    const { SECTION_ID, AVAILABLE, STATUS, SUMMARY, BODY } = process.env
    if (AVAILABLE !== 'true') {
        await markUnmeasured(SECTION_ID)
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
