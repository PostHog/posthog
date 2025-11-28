#!/usr/bin/env node

const { execSync } = require('child_process');

// Parse command-line arguments
const [workflowType, mode, changesJson, prNumber, repo, commitSha, snapshotSha] = process.argv.slice(2);

if (process.argv.length !== 8 && process.argv.length !== 9) {
    console.error('Usage: post-snapshot-comment.js <workflow_type> <mode> <changes_json> <pr_number> <repo> <commit_sha> [snapshot_sha]');
    process.exit(1);
}

// Parse changes JSON
const changes = JSON.parse(changesJson);
const { total, added, modified, deleted } = changes;

// Set workflow-specific labels
const config = workflowType === 'storybook' ? {
    label: 'Storybook',
    type: 'UI snapshots',
    filesFilter: 'frontend/__snapshots__/',
    localCmd: '`pnpm storybook`',
} : {
    label: 'Playwright E2E',
    type: 'E2E screenshots',
    filesFilter: 'playwright/',
    localCmd: '`pnpm --filter=@posthog/playwright exec playwright test --ui`',
};

// UPDATE mode: snapshots were updated
if (mode !== 'update') {
    console.error(`Error: Unknown mode: ${mode}`);
    process.exit(1);
}

if (total === 0) {
    console.error('No snapshot changes, skipping comment');
    process.exit(0);
}

const comment = `### Visual regression: ${config.label} ${config.type} updated

**Mode:** \`UPDATE\` (triggered by human commit [${commitSha.substring(0, 7)}](https://github.com/${repo}/commit/${commitSha}))

**Changes:** ${total} snapshots (${modified} modified, ${added} added, ${deleted} deleted)

**What this means:**
- Snapshots have been automatically updated to match current rendering
- Next CI run will switch to CHECK mode to verify stability
- If snapshots change again, CHECK mode will fail (indicates flapping)

**Next steps:**
- Review the changes to ensure they're intentional
- Approve if changes match your expectations
- If unexpected, investigate component rendering

[Review snapshot changes →](https://github.com/${repo}/commit/${snapshotSha || commitSha})`;

// Post comment using gh CLI
try {
    execSync(`gh pr comment ${prNumber} --repo ${repo} --body-file -`, {
        input: comment,
        encoding: 'utf-8',
        stdio: ['pipe', 'inherit', 'inherit']
    });
    console.error(`Posted comment to PR #${prNumber}`);
} catch (error) {
    console.error(`Failed to post comment: ${error.message}`);
    process.exit(1);
}
