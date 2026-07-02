#!/usr/bin/env node
import { postSection } from '../../frontend/bin/ci-report/update-ci-report.mjs'

const [workflowType, mode, changesJson, prNumber, repo, commitSha, snapshotSha] = process.argv.slice(2)

if (process.argv.length !== 8 && process.argv.length !== 9) {
    console.error(
        'Usage: post-snapshot-section.mjs <workflow_type> <mode> <changes_json> <pr_number> <repo> <commit_sha> [snapshot_sha]'
    )
    process.exit(0)
}

if (mode !== 'update') {
    console.error(`Unknown mode: ${mode} — skipping snapshot section.`)
    process.exit(0)
}

const changes = JSON.parse(changesJson)
const { total, added, modified, deleted } = changes

if (total === 0) {
    console.info('No snapshot changes — nothing to post.')
    process.exit(0)
}

const CONFIGS = {
    storybook: {
        id: 'storybook-snapshots',
        label: 'Storybook',
        type: 'UI snapshots',
        headerPrefix: 'Visual regression',
        whatThisMeans: `- Snapshots have been automatically updated to match current rendering
- Next CI run will switch to CHECK mode to verify stability
- If snapshots change again, CHECK mode will fail (indicates flapping)`,
        nextSteps: `- Review the changes to ensure they're intentional
- Approve if changes match your expectations
- If unexpected, investigate component rendering`,
    },
    backend: {
        id: 'backend-snapshots',
        label: 'Backend',
        type: 'query snapshots',
        headerPrefix: 'Query snapshots',
        whatThisMeans: `- Query snapshots have been automatically updated to match current output
- These changes reflect modifications to database queries or schema`,
        nextSteps: `- Review the query changes to ensure they're intentional
- If unexpected, investigate what caused the query to change`,
    },
    playwright: {
        id: 'playwright-snapshots',
        label: 'Playwright E2E',
        type: 'E2E screenshots',
        headerPrefix: 'Visual regression',
        whatThisMeans: `- Snapshots have been automatically updated to match current rendering
- Next CI run will switch to CHECK mode to verify stability
- If snapshots change again, CHECK mode will fail (indicates flapping)`,
        nextSteps: `- Review the changes to ensure they're intentional
- Approve if changes match your expectations
- If unexpected, investigate component rendering`,
    },
}

const config = CONFIGS[workflowType]
if (!config) {
    console.error(`Unknown workflow type: ${workflowType} — skipping snapshot section.`)
    process.exit(0)
}

const body = `### ${config.headerPrefix}: ${config.label} ${config.type} updated

**Changes:** ${total} snapshots (${modified} modified, ${added} added, ${deleted} deleted)

**What this means:**
${config.whatThisMeans}

**Next steps:**
${config.nextSteps}

[Review snapshot changes →](https://github.com/${repo}/commit/${snapshotSha || commitSha})`

const summary = `${total} updated (${added} added, ${deleted} deleted)`

await postSection({
    id: config.id,
    status: 'warn',
    summary,
    body,
})
