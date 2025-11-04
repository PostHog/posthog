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

# Check if current commit author is the bot
AUTHOR=$(git log -1 --pretty=format:'%an')

if [[ "$AUTHOR" == *"github-actions"* ]] || [[ "$AUTHOR" == *"[bot]"* ]]; then
    # Bot commit → CHECK mode
    echo "check"
else
    # Human commit → UPDATE mode
    echo "update"
fi
