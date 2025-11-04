#!/usr/bin/env node

const { execSync } = require('child_process');

// Parse command-line arguments
const [workflowType, mode, changesJson, prNumber, repo, commitSha] = process.argv.slice(2);

if (process.argv.length !== 8) {
    console.error('Usage: post-snapshot-comment.js <workflow_type> <mode> <changes_json> <pr_number> <repo> <commit_sha>');
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

// Build comment based on mode
let comment;

if (mode === 'update') {
    // UPDATE mode: snapshots were updated
    if (total === 0) {
        console.error('No snapshot changes, skipping comment');
        process.exit(0);
    }

    comment = `### Visual regression: ${config.label} ${config.type} updated

**Mode:** UPDATE (triggered by human commit)

**Changes:** ${total} snapshots (${modified} modified, ${added} added, ${deleted} deleted)

**What this means:**
- Snapshots have been automatically updated to match current rendering
- Next CI run will switch to CHECK mode to verify stability
- If snapshots change again, CHECK mode will fail (indicates flapping)

**Next steps:**
- Review the changes to ensure they're intentional
- Approve if changes match your expectations
- If unexpected, investigate component rendering

[Review snapshot changes →](https://github.com/${repo}/pull/${prNumber}/files#:~:text=${config.filesFilter})`;

} else if (mode === 'check') {
    // CHECK mode: snapshots verified successfully
    comment = `### Visual regression: ${config.label} ${config.type} verified ✓

**Mode:** CHECK (triggered by bot commit)

All snapshots match exactly - no rendering instability detected

**What this means:**
- Snapshots from previous update are stable and consistent
- No flapping or non-deterministic rendering
- Safe to merge

Ready to merge!`;

} else if (mode === 'check-failed') {
    // CHECK mode failed: snapshots differ (flapping)
    const filesList = changes.files
        .slice(0, 20)
        .map(f => `- \`${f.path.replace(config.filesFilter, '')}\``)
        .join('\n');

    const moreFiles = changes.files.length > 20
        ? `\n- _(and ${changes.files.length - 20} more)_`
        : '';

    comment = `### Visual regression: ${config.label} ${config.type} failed verification ✗

**Mode:** CHECK (triggered by bot commit)

**Problem:** Snapshots differ from previous run - indicates flapping/instability

**Changes:** ${total} snapshots still changing
${filesList}${moreFiles}

**What this means:**
- These snapshots are non-deterministic (timing issues, animations, etc.)
- This prevents reliable verification and blocks merge
- Human intervention required

**How to fix:**
1. Run ${config.localCmd} locally
2. Investigate flaky stories/tests (list above)
3. Fix underlying issues:
   - Add proper waits for async operations
   - Stabilize animations (disable or wait for completion)
   - Use CSS container queries instead of ResizeObserver where possible
   - Check for race conditions in rendering
4. Push your fix (resets to UPDATE mode)

**Do NOT just re-run CI** - fix the root cause first

Workflow blocked until fixed.`;

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
