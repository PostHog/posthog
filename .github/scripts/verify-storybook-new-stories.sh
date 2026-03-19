#!/bin/bash
set -euo pipefail

# Verify changed Storybook story files are stable by re-running them multiple times.
# Catches flaky snapshots before they land on master.
#
# Usage:
#   verify-storybook-new-stories.sh <base_sha> [repeat_count]
#
# Example:
#   .github/scripts/verify-storybook-new-stories.sh origin/master 3

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <base_sha> [repeat_count]" >&2
    exit 1
fi

BASE_SHA="$1"
REPEAT_COUNT="${2:-3}"

if ! [[ "$REPEAT_COUNT" =~ ^[0-9]+$ ]] || [ "$REPEAT_COUNT" -lt 1 ]; then
    echo "Error: repeat_count must be a positive integer" >&2
    exit 1
fi

echo "Detecting changed story files since $BASE_SHA..."

# All story files touched by the PR (added or modified).
changed_story_files=$(git diff --name-only "$BASE_SHA..HEAD" -- '*.stories.tsx' '*.stories.ts')

if [ -z "$changed_story_files" ]; then
    echo "No changed story files found — skipping flake verification"
    exit 0
fi

# Filter to files that still exist (skip deleted).
declare -a stories_to_verify=()
while IFS= read -r story_file; do
    if [ ! -f "$story_file" ]; then
        echo "Skipping $story_file (deleted)"
        continue
    fi
    stories_to_verify+=("$story_file")
done <<< "$changed_story_files"

if [ ${#stories_to_verify[@]} -eq 0 ]; then
    echo "No runnable story files to verify"
    exit 0
fi

echo "Verifying ${#stories_to_verify[@]} file(s) × $REPEAT_COUNT runs:"
printf "  %s\n" "${stories_to_verify[@]}"

# Build a regex pattern matching any of the changed story files.
# test-storybook wraps Jest — pass Jest options after -- separator.
pattern=""
for story in "${stories_to_verify[@]}"; do
    escaped=$(echo "$story" | sed 's/\./\\./g')
    if [ -n "$pattern" ]; then
        pattern="${pattern}|${escaped}"
    else
        pattern="$escaped"
    fi
done

echo ""
echo "testPathPattern: $pattern"
echo ""

# Build products once before the loop — test:visual:ci:verify rebuilds each time.
pnpm --filter=@posthog/storybook run build:products

# Run the stories REPEAT_COUNT times. Each run does a full snapshot comparison.
# If any run fails, the story is flaky.
failed_runs=0
for run in $(seq 1 "$REPEAT_COUNT"); do
    echo "=== Run $run/$REPEAT_COUNT ==="

    set +e
    # Run test-storybook directly (skipping build:products which we already did).
    # pipefail is set at script level so tee preserves the exit code.
    pnpm --filter=@posthog/storybook exec test-storybook \
        --ci --no-index-json --maxWorkers=1 \
        --browsers chromium \
        -- --testPathPattern "$pattern" 2>&1 | tee "/tmp/storybook-verify-run${run}.log"
    exit_code=${PIPESTATUS[0]}
    set -e

    if [ $exit_code -ne 0 ]; then
        echo "Run $run failed (exit code $exit_code)"
        failed_runs=$((failed_runs + 1))
    else
        echo "Run $run passed"
    fi

    echo ""
done

if [ "$failed_runs" -gt 0 ]; then
    echo ""
    echo "Flake verification failed — $failed_runs/$REPEAT_COUNT runs failed"
    echo "Flaky snapshots must be fixed before merging."
    exit 1
fi

echo "Flake verification passed — all $REPEAT_COUNT runs stable"
