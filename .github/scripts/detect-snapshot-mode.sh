#!/bin/bash
set -e

# Detect whether to run visual regression tests in CHECK or UPDATE mode
#
# Logic:
#   - Human commit → UPDATE mode (snapshots can be updated and committed)
#   - Bot commit   → CHECK mode (snapshots must match exactly, fail if different)
#
# This prevents infinite loops:
#   Human changes code → bot updates snapshots → bot commit triggers check →
#   if snapshots still differ (flapping) → CHECK mode fails hard → no new commit
#
# Exit codes:
#   0 = success (mode printed to stdout)
#   1 = error (no commit history available)

# Ensure we have full git history
# Both workflows use fetch-depth: 0, but verify anyway
if ! git rev-parse HEAD >/dev/null 2>&1; then
    echo "Error: Not in a git repository or HEAD not available" >&2
    exit 1
fi

# Find last commit that wasn't from github-actions bot
# This determines our mode: if last commit was human, we're in UPDATE mode
last_human_commit=$(git log --pretty=format:"%H" --perl-regexp --author='^(?!github-actions)' -1 2>/dev/null || echo "")

if [ -z "$last_human_commit" ]; then
    echo "Error: No human commits found in history" >&2
    echo "This might indicate a shallow checkout or bot-only repository" >&2
    exit 1
fi

# Check if current HEAD is the human commit
current_commit=$(git rev-parse HEAD)

if [ "$current_commit" = "$last_human_commit" ]; then
    # Last commit was human → UPDATE mode
    echo "update"
else
    # Last commit was bot → CHECK mode
    echo "check"
fi
