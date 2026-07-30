#!/usr/bin/env node
import fs from 'node:fs'

import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const MARKER_LINE = '<!-- ch-migration-sql -->'
// The section shares one comment (GitHub caps bodies at 65536 chars) with every other
// section plus marker/meta overhead — a body sized for a standalone comment would make
// the shared PATCH fail and freeze the whole report until the SQL shrinks.
const LIMIT = 30000

const hasChanges = process.env.HAS_CHANGES === 'true'

if (!hasChanges) {
    // Migrations were added then removed in a later push — mark the section resolved.
    await clearSectionIfPresent({
        id: 'ch-migration-sql',
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
