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

# Filter to files that still exist (skip deleted) and that the main storybook app
# actually serves — must mirror the `stories` globs in common/storybook/.storybook/main.ts.
# Stories from other storybook apps (e.g. packages/quill/apps/storybook) aren't in the
# test runner's testMatch, so including them makes Jest exit 1 with "No tests found".
declare -a stories_to_verify=()
while IFS= read -r story_file; do
    if [ ! -f "$story_file" ]; then
        echo "Skipping $story_file (deleted)"
        continue
    fi
    case "$story_file" in
        frontend/src/* | products/*/frontend/* | products/*/mcp/* | packages/quill/packages/charts/src/*)
            stories_to_verify+=("$story_file")
            ;;
        *)
            echo "Skipping $story_file (not served by the main storybook app)"
            ;;
    esac
done <<< "$changed_story_files"

if [ ${#stories_to_verify[@]} -eq 0 ]; then
    echo "No runnable story files to verify"
    exit 0
fi

# Scale repeats down for large story sets so the job fits its time budget
# (runs are sequential with --maxWorkers=1). Small PRs keep full verification;
# mass refactors degrade to fewer passes instead of timing out.
file_count=${#stories_to_verify[@]}
if [ "$file_count" -gt 30 ] && [ "$REPEAT_COUNT" -gt 1 ]; then
    echo "NOTE: $file_count story files changed — reducing repeat count from $REPEAT_COUNT to 1 to fit the job time budget"
    REPEAT_COUNT=1
elif [ "$file_count" -gt 10 ] && [ "$REPEAT_COUNT" -gt 2 ]; then
    echo "NOTE: $file_count story files changed — reducing repeat count from $REPEAT_COUNT to 2 to fit the job time budget"
    REPEAT_COUNT=2
fi

echo "Verifying $file_count file(s) × $REPEAT_COUNT runs:"
printf "  %s\n" "${stories_to_verify[@]}"

# Build one escaped path regex per changed story file.
# These are passed as separate positional Jest patterns (OR-matched) rather than a
# single `|`-joined regex: a literal `|` survives into a downstream shell layer
# (pnpm exec / test-storybook re-invoking jest) where it's parsed as a pipe, which
# breaks the command. Positional patterns also sidestep the jest 30 rename of
# `--testPathPattern` to `--testPathPatterns`.
declare -a pattern_args=()
for story in "${stories_to_verify[@]}"; do
    pattern_args+=("$(echo "$story" | sed 's/\./\\./g')")
done

echo ""
echo "testPathPatterns: ${pattern_args[*]}"
echo ""

# Run the stories REPEAT_COUNT times. Each run does a full snapshot comparison.
# If any run fails, the story is flaky.
failed_runs=0
for run in $(seq 1 "$REPEAT_COUNT"); do
    echo "=== Run $run/$REPEAT_COUNT ==="

    # First run: --updateSnapshot to create baselines for new stories.
    # Subsequent runs: --ci to verify the snapshot is stable.
    if [ "$run" -eq 1 ]; then
        snapshot_flag="--updateSnapshot"
    else
        snapshot_flag="--ci"
    fi

    set +e
    # Run test-storybook directly (tests a pre-built storybook dist served over http-server).
    # pipefail is set at script level so tee preserves the exit code.
    # --passWithNoTests: changed stories may live in a separate storybook that
    # the main runner's testMatch doesn't cover. Those are verified by their own
    # CI, so finding no matching tests here is not a failure.
    pnpm --filter=@posthog/storybook exec test-storybook \
        $snapshot_flag --no-index-json --maxWorkers=1 \
        --browsers chromium \
        -- "${pattern_args[@]}" --passWithNoTests 2>&1 | tee "/tmp/storybook-verify-run${run}.log"
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
