#!/usr/bin/env node
// Generic one-shot reminder poster. Usage:
//   BODY="<markdown>" node post-reminder-section.mjs <section-id> <status> [<summary>]
//   node post-reminder-section.mjs <section-id> --clear [<summary>]
// The section id must be registered in SECTIONS in update-ci-report.mjs.
//
// --clear marks a previously posted reminder as resolved (status ok) — but only when
// the report already carries the section. Without that guard every PR whose check
// passes would gain a "nothing to see here" section; with it, a reminder that was
// real on one push cannot linger as a stale warning after a later push fixes it.
import {
    isReportComment,
    listPrComments,
    parseSections,
    postSection,
    resolvePrContext,
} from '../../frontend/bin/ci-report/update-ci-report.mjs'

const [id, status, summary] = process.argv.slice(2)
if (!id || !status) {
    console.error('Usage: BODY="<markdown>" node post-reminder-section.mjs <id> <status|--clear> [<summary>]')
    process.exit(1)
}

if (status === '--clear') {
    const context = resolvePrContext('reminder clear')
    if (!context) {
        process.exit(0)
    }
    let reportComment
    try {
        reportComment = (await listPrComments(context)).find(isReportComment)
    } catch (err) {
        console.warn(`Could not read PR comments: ${err.message}`)
        process.exit(0)
    }
    if (!reportComment || !parseSections(reportComment.body).has(id)) {
        console.info(`No existing "${id}" section — nothing to clear.`)
        process.exit(0)
    }
    await postSection({
        id,
        status: 'ok',
        summary: summary ?? 'resolved',
        body: process.env.BODY || 'Resolved in the latest push.',
    })
    process.exit(0)
}

const body = process.env.BODY
if (!body) {
    console.error('BODY env var is required')
    process.exit(1)
}

await postSection({ id, status, summary: summary ?? '', body })
