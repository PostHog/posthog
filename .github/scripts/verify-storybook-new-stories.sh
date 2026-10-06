#!/bin/bash
set -euo pipefail

# Verify changed Storybook story files are stable by re-running them multiple times.
# Catches flaky snapshots and webkit-only breaks before they land on master.
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

echo "Verifying $file_count file(s): $REPEAT_COUNT chromium run(s), then 1 webkit run:"
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

# Usage: run_stories <browser> <run_name> <snapshot_flag>
run_stories() {
    local browser="$1" run_name="$2" snapshot_flag="$3"
    echo "=== $run_name ==="

    # Run test-storybook directly (tests a pre-built storybook dist served over http-server).
    # pipefail is set at script level so tee preserves the exit code.
    # --passWithNoTests: changed stories may live in a separate storybook that
    # the main runner's testMatch doesn't cover. Those are verified by their own
    # CI, so finding no matching tests here is not a failure.
    # STORYBOOK_SKIP_TAGS must match the visual-regression shards in ci-storybook.yml,
    # so that a story tagged test-skip-<browser> is skipped here too.
    STORYBOOK_SKIP_TAGS="test-skip,test-skip-${browser}" \
        pnpm --filter=@posthog/storybook exec test-storybook \
        "$snapshot_flag" --no-index-json --maxWorkers=1 \
        --browsers "$browser" \
        -- "${pattern_args[@]}" --passWithNoTests 2>&1 | tee "/tmp/storybook-verify-${run_name}.log"
}

declare -a failed_runs=()

# Run the stories REPEAT_COUNT times in chromium. Each run does a full snapshot comparison.
# If any run fails, the story is flaky.
for run in $(seq 1 "$REPEAT_COUNT"); do
    # First run: --updateSnapshot to create baselines for new stories.
    # Subsequent runs: --ci to verify the snapshot is stable.
    if [ "$run" -eq 1 ]; then
        snapshot_flag="--updateSnapshot"
    else
        snapshot_flag="--ci"
    fi

    run_name="chromium-run-$run"
    if run_stories chromium "$run_name" "$snapshot_flag"; then
        echo "$run_name passed"
    else
        echo "$run_name failed"
        failed_runs+=("$run_name")
    fi
    echo ""
done

# The merge queue is the first full-matrix run that includes webkit, so a story that breaks
# only in webkit must fail here. Otherwise it fails the queue batch of every PR behind it.
# One run is enough, because the stories take no webkit snapshot that a second run could
# compare against, and the test runner already retries a failed story.
if run_stories webkit webkit-run-1 --updateSnapshot; then
    echo "webkit-run-1 passed"
else
    echo "webkit-run-1 failed"
    failed_runs+=(webkit-run-1)
fi
echo ""

if [ "${#failed_runs[@]}" -gt 0 ]; then
    echo "Flake verification failed in: ${failed_runs[*]}"
    echo "A chromium failure is a flaky or broken snapshot. A webkit failure is a story that does not render or play in webkit."
    echo "Fix the story before merging."
    exit 1
fi

echo "Flake verification passed — $REPEAT_COUNT chromium run(s) and 1 webkit run stable"
