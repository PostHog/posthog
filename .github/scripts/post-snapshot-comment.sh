#!/bin/bash
set -e

# Post visual regression comment to PR
#
# Usage: post-snapshot-comment.sh <workflow_type> <mode> <changes_json> <pr_number> <repo> <commit_sha>
#
# workflow_type: "storybook" or "playwright"
# mode: "update", "check", or "check-failed"
# changes_json: JSON from count-snapshot-changes.sh
# pr_number: GitHub PR number
# repo: GitHub repo (owner/name)
# commit_sha: Triggering commit SHA

if [ $# -ne 6 ]; then
    echo "Usage: $0 <workflow_type> <mode> <changes_json> <pr_number> <repo> <commit_sha>" >&2
    exit 1
fi

WORKFLOW_TYPE="$1"
MODE="$2"
CHANGES_JSON="$3"
PR_NUMBER="$4"
REPO="$5"
COMMIT_SHA="$6"

# Parse JSON
TOTAL=$(echo "$CHANGES_JSON" | jq -r '.total')
ADDED=$(echo "$CHANGES_JSON" | jq -r '.added')
MODIFIED=$(echo "$CHANGES_JSON" | jq -r '.modified')
DELETED=$(echo "$CHANGES_JSON" | jq -r '.deleted')

# Set workflow-specific labels
if [ "$WORKFLOW_TYPE" = "storybook" ]; then
    WORKFLOW_LABEL="Storybook"
    SNAPSHOT_TYPE="UI snapshots"
    FILES_FILTER="frontend/__snapshots__/"
    LOCAL_CMD="\`pnpm storybook\`"
elif [ "$WORKFLOW_TYPE" = "playwright" ]; then
    WORKFLOW_LABEL="Playwright E2E"
    SNAPSHOT_TYPE="E2E screenshots"
    FILES_FILTER="playwright/"
    LOCAL_CMD="\`pnpm --filter=@posthog/playwright exec playwright test --ui\`"
else
    echo "Error: Unknown workflow type: $WORKFLOW_TYPE" >&2
    exit 1
fi

# Generate comment based on mode
if [ "$MODE" = "update" ]; then
    # UPDATE mode: snapshots were updated
    if [ "$TOTAL" -eq 0 ]; then
        # No changes, skip comment
        echo "No snapshot changes, skipping comment" >&2
        exit 0
    fi

    COMMENT=$(cat <<EOF
### Visual regression: $WORKFLOW_LABEL ${SNAPSHOT_TYPE} updated

**Mode:** UPDATE (triggered by human commit)

**Changes:** $TOTAL snapshots ($MODIFIED modified, $ADDED added, $DELETED deleted)

**What this means:**
- Snapshots have been automatically updated to match current rendering
- Next CI run will switch to CHECK mode to verify stability
- If snapshots change again, CHECK mode will fail (indicates flapping)

**Next steps:**
- Review the changes to ensure they're intentional
- Approve if changes match your expectations
- If unexpected, investigate component rendering

[Review snapshot changes →](https://github.com/$REPO/pull/$PR_NUMBER/files#:~:text=$FILES_FILTER)
EOF
)

elif [ "$MODE" = "check" ]; then
    # CHECK mode: snapshots verified successfully
    COMMENT=$(cat <<EOF
### Visual regression: $WORKFLOW_LABEL ${SNAPSHOT_TYPE} verified ✓

**Mode:** CHECK (triggered by bot commit)

All snapshots match exactly - no rendering instability detected

**What this means:**
- Snapshots from previous update are stable and consistent
- No flapping or non-deterministic rendering
- Safe to merge

Ready to merge!
EOF
)

elif [ "$MODE" = "check-failed" ]; then
    # CHECK mode failed: snapshots differ (flapping)
    # Get list of changed files
    FILES_LIST=$(echo "$CHANGES_JSON" | jq -r '.files[] | "- `\(.path | sub("^'$FILES_FILTER'"; ""))`"' | head -20)
    if [ $(echo "$CHANGES_JSON" | jq -r '.files | length') -gt 20 ]; then
        FILES_LIST="$FILES_LIST
- _(and $(($(echo "$CHANGES_JSON" | jq -r '.files | length') - 20)) more)_"
    fi

    COMMENT=$(cat <<EOF
### Visual regression: $WORKFLOW_LABEL ${SNAPSHOT_TYPE} failed verification ✗

**Mode:** CHECK (triggered by bot commit)

**Problem:** Snapshots differ from previous run - indicates flapping/instability

**Changes:** $TOTAL snapshots still changing
$FILES_LIST

**What this means:**
- These snapshots are non-deterministic (timing issues, animations, etc.)
- This prevents reliable verification and blocks merge
- Human intervention required

**How to fix:**
1. Run $LOCAL_CMD locally
2. Investigate flaky stories/tests (list above)
3. Fix underlying issues:
   - Add proper waits for async operations
   - Stabilize animations (disable or wait for completion)
   - Use CSS container queries instead of ResizeObserver where possible
   - Check for race conditions in rendering
4. Push your fix (resets to UPDATE mode)

**Do NOT just re-run CI** - fix the root cause first

Workflow blocked until fixed.
EOF
)

else
    echo "Error: Unknown mode: $MODE" >&2
    exit 1
fi

# Post comment using gh CLI
echo "$COMMENT" | gh pr comment "$PR_NUMBER" --repo "$REPO" --body-file -

echo "Posted comment to PR #$PR_NUMBER" >&2
