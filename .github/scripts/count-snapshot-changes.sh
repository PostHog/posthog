#!/bin/bash
set -e

# Count snapshot changes
#
# Usage: count-snapshot-changes.sh <snapshot_directory>
# Output: JSON with {added, modified, deleted, total, files: [{path, status, shard}]}
#
# This script counts git diff changes in snapshot directory and outputs JSON.
# Note: PNG optimization is now handled in shard jobs before patch creation.

if [ $# -ne 1 ]; then
    echo "Usage: $0 <snapshot_directory>" >&2
    exit 1
fi

SNAPSHOT_DIR="$1"

if [ ! -d "$SNAPSHOT_DIR" ]; then
    echo "Error: Directory $SNAPSHOT_DIR does not exist" >&2
    exit 1
fi

# Count changes (snapshots already optimized in shard jobs)
echo "Checking for changes in $SNAPSHOT_DIR..." >&2
git diff --cached --name-status "$SNAPSHOT_DIR" > /tmp/snapshot-diff.txt || true

ADDED=$(grep '^A' /tmp/snapshot-diff.txt | wc -l | xargs)
MODIFIED=$(grep '^M' /tmp/snapshot-diff.txt | wc -l | xargs)
DELETED=$(grep '^D' /tmp/snapshot-diff.txt | wc -l | xargs)
TOTAL=$((ADDED + MODIFIED + DELETED))

DIFF_FILE="/tmp/snapshot-diff.txt"

# Build JSON array of changed files using jq for safe JSON construction
FILES=$(while IFS= read -r line; do
    if [ -z "$line" ]; then
        continue
    fi

    status=$(echo "$line" | awk '{print $1}')
    path=$(echo "$line" | awk '{print $2}')

    # Extract shard number if present in filename (e.g., "shard-1-of-16")
    shard=""
    if [[ "$path" =~ shard-([0-9]+) ]]; then
        shard="${BASH_REMATCH[1]}"
    fi

    # Use jq to safely construct JSON object
    if [ -n "$shard" ]; then
        jq -n --arg p "$path" --arg s "$status" --arg sh "$shard" '{path: $p, status: $s, shard: ($sh | tonumber)}'
    else
        jq -n --arg p "$path" --arg s "$status" '{path: $p, status: $s}'
    fi
done < "$DIFF_FILE" | jq -s '.')

# Output JSON using jq with compact output
jq -nc \
    --argjson a "$ADDED" \
    --argjson m "$MODIFIED" \
    --argjson d "$DELETED" \
    --argjson t "$TOTAL" \
    --argjson f "$FILES" \
    '{added: $a, modified: $m, deleted: $d, total: $t, files: $f}'
