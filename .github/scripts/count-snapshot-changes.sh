#!/bin/bash
set -e

# Count snapshot changes and optimize with OptiPNG
#
# Usage: count-snapshot-changes.sh <snapshot_directory>
# Output: JSON with {added, modified, deleted, total, files: [{path, status, shard}]}
#
# This script:
# 1. Counts git diff changes in snapshot directory
# 2. Runs OptiPNG on new/modified snapshots
# 3. Re-counts after optimization (OptiPNG may eliminate diffs)
# 4. Outputs JSON for consumption by other scripts

if [ $# -ne 1 ]; then
    echo "Usage: $0 <snapshot_directory>" >&2
    exit 1
fi

SNAPSHOT_DIR="$1"

if [ ! -d "$SNAPSHOT_DIR" ]; then
    echo "Error: Directory $SNAPSHOT_DIR does not exist" >&2
    exit 1
fi

# Count changes before OptiPNG
echo "Checking for changes in $SNAPSHOT_DIR..." >&2
git diff --cached --name-status "$SNAPSHOT_DIR" > /tmp/snapshot-diff.txt || true

ADDED=$(grep '^A' /tmp/snapshot-diff.txt | wc -l | xargs)
MODIFIED=$(grep '^M' /tmp/snapshot-diff.txt | wc -l | xargs)
DELETED=$(grep '^D' /tmp/snapshot-diff.txt | wc -l | xargs)

# Track which file to read from for JSON building
DIFF_FILE="/tmp/snapshot-diff.txt"

# Run OptiPNG if there are added or modified files
if [ "$ADDED" -gt 0 ] || [ "$MODIFIED" -gt 0 ]; then
    echo "Running OptiPNG optimization on $((ADDED + MODIFIED)) files..." >&2
    sudo apt-get update -qq && sudo apt-get install -y -qq optipng >/dev/null 2>&1 || true

    # Find PNG files that were added or modified
    while IFS= read -r line; do
        status=$(echo "$line" | awk '{print $1}')
        file=$(echo "$line" | awk '{print $2}')
        if [[ "$status" == "A" || "$status" == "M" ]] && [[ "$file" == *.png ]]; then
            if [ -f "$file" ]; then
                optipng -clobber -o4 -strip all "$file" 2>/dev/null || true
            fi
        fi
    done < /tmp/snapshot-diff.txt

    # Re-count after OptiPNG (may have eliminated some diffs)
    git diff --cached --name-status "$SNAPSHOT_DIR" > /tmp/snapshot-diff-after.txt || true
    DIFF_FILE="/tmp/snapshot-diff-after.txt"
    ADDED=$(grep '^A' /tmp/snapshot-diff-after.txt | wc -l | xargs)
    MODIFIED=$(grep '^M' /tmp/snapshot-diff-after.txt | wc -l | xargs)
    DELETED=$(grep '^D' /tmp/snapshot-diff-after.txt | wc -l | xargs)
fi

TOTAL=$((ADDED + MODIFIED + DELETED))

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
