#!/usr/bin/env node

const { execSync } = require('child_process');

// Parse command-line arguments
const [workflowType, mode, changesJson, prNumber, repo, commitSha, snapshotSha] = process.argv.slice(2);

if (process.argv.length !== 8 && process.argv.length !== 9) {
    console.error('Usage: post-snapshot-comment.js <workflow_type> <mode> <changes_json> <pr_number> <repo> <commit_sha> [snapshot_sha]');
    process.exit(1);
}

// Parse changes JSON (may be empty in check-failed mode)
const changes = changesJson ? JSON.parse(changesJson) : { total: 0, added: 0, modified: 0, deleted: 0, files: [] };
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

// Build comment based on mode
let comment;

if (mode === 'update') {
    // UPDATE mode: snapshots were updated
    if (total === 0) {
        console.error('No snapshot changes, skipping comment');
        process.exit(0);
    }

    comment = `### Visual regression: ${config.label} ${config.type} updated

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

} else if (mode === 'check') {
    // CHECK mode: snapshots verified successfully
    comment = `### Visual regression: ${config.label} ${config.type} verified ✓

**Mode:** \`CHECK\` (triggered by bot commit [${commitSha.substring(0, 7)}](https://github.com/${repo}/commit/${commitSha}))

All snapshots match exactly - no rendering instability detected

**What this means:**
- Snapshots from previous update are stable and consistent
- No flapping or non-deterministic rendering
- Safe to merge

Ready to merge!`;

} else if (mode === 'check-failed') {
    // CHECK mode failed: snapshots don't match current rendering
    comment = `### Visual regression: ${config.label} ${config.type} verification failed ✗

**Mode:** \`CHECK\` (triggered by bot commit [${commitSha.substring(0, 7)}](https://github.com/${repo}/commit/${commitSha}))

**Problem:** Current rendering doesn't match committed snapshots

**What this means:**
- The verification run produced different output than what was committed in UPDATE mode
- This could indicate non-deterministic rendering (timing, animations, randomness)
- OR the UPDATE run may have missed some rendering changes
- Manual review required to determine cause

**How to fix:**
1. Check CI logs to see which snapshots failed verification
2. Run ${config.localCmd} locally to reproduce
3. Determine if it's flapping (run multiple times) or a missed change
4. If flapping: Fix the root cause (waits, animations, race conditions)
5. If missed change: Push any code fix to trigger UPDATE mode again
6. If uncertain: Push an empty commit to re-run UPDATE mode: \`git commit --allow-empty -m "chore: re-run visual regression"\`

Workflow blocked until resolved.`;

} else {
    console.error(`Error: Unknown mode: ${mode}`);
    process.exit(1);
}

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
