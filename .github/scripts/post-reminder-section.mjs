#!/usr/bin/env node
// Generic one-shot reminder poster. Usage:
//   BODY="<markdown>" node post-reminder-section.mjs <section-id> <status> [<summary>]
//   node post-reminder-section.mjs <section-id> --clear [<summary>]
// The section id must be registered in SECTIONS in update-ci-report.mjs.
//
import { clearSectionIfPresent, postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const [id, status, summary] = process.argv.slice(2)
if (!id || !status) {
    console.error('Usage: BODY="<markdown>" node post-reminder-section.mjs <id> <status|--clear> [<summary>]')
    process.exit(1)
}

if (status === '--clear') {
    await clearSectionIfPresent({
        id,
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
