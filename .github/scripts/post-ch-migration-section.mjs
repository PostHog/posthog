#!/usr/bin/env node
import fs from 'node:fs'

import {
    isReportComment,
    listPrComments,
    parseSections,
    postSection,
    resolvePrContext,
} from '../../frontend/bin/ci-report/update-ci-report.mjs'

const MARKER_LINE = '<!-- ch-migration-sql -->'
const LIMIT = 65000

const hasChanges = process.env.HAS_CHANGES === 'true'

if (!hasChanges) {
    // No migrations changed. The engine can't remove a section, so only post a
    // "none" state when the report already carries a ch-migration-sql section
    // (migrations were added then removed in a later push). Otherwise stay silent
    // rather than adding an empty section to every backend PR.
    const context = resolvePrContext('CH migration section')
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
    if (!reportComment || !parseSections(reportComment.body).has('ch-migration-sql')) {
        console.info('No ClickHouse migrations changed and no existing section — nothing to post.')
        process.exit(0)
    }
    await postSection({
        id: 'ch-migration-sql',
        status: 'ok',
        summary: 'none',
        body: 'No ClickHouse migrations in the latest push.',
    })
    process.exit(0)
}

if (!fs.existsSync('ch_migration_sql_comment.md')) {
    console.info('No ch_migration_sql_comment.md found — nothing to post.')
    process.exit(0)
}

const raw = fs.readFileSync('ch_migration_sql_comment.md', 'utf8')
let body = raw
    .split('\n')
    .filter((line) => line.trim() !== MARKER_LINE)
    .join('\n')
    .trim()

if (body.length > LIMIT) {
    const runUrl = `${process.env.GITHUB_SERVER_URL}/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}`
    body = body.slice(0, LIMIT - 400) + `\n\n_…truncated. See the full SQL in the [workflow logs](${runUrl})._`
}

const count = Number.parseInt(process.env.CH_MIGRATION_COUNT || '', 10)
const summary = Number.isFinite(count) && count > 0 ? `${count} migration(s)` : 'migration SQL rendered'

await postSection({
    id: 'ch-migration-sql',
    status: 'info',
    summary,
    body,
})
