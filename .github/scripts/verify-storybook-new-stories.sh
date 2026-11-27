#!/bin/bash
set -euo pipefail

# Verify changed Storybook story files are stable by re-running them multiple times.
# Catches flaky snapshots and webkit-only breaks before they land on master.
#
# Usage:
#   verify-storybook-new-stories.sh <base_sha> [repeat_count]
#
# Pass the merge base, not the base branch tip. A branch tip that moved on since the
# fork point makes its own story changes look like this branch's.
#
# Example:
#   .github/scripts/verify-storybook-new-stories.sh "$(git merge-base origin/master HEAD)" 3

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

# Must mirror the `stories` globs in common/storybook/.storybook/main.ts.
# Stories from other storybook apps (e.g. packages/quill/apps/storybook) aren't in the
# test runner's testMatch, so including them makes Jest exit 1 with "No tests found".
is_served_story_file() {
    case "$1" in
        frontend/src/* | products/*/frontend/* | products/*/mcp/* | packages/quill/packages/charts/src/*)
            return 0
            ;;
    esac
    return 1
}

echo "Detecting changed story files since $BASE_SHA..."

# All story files touched by the PR (added or modified).
changed_story_files=$(git diff --name-only "$BASE_SHA..HEAD" -- '*.stories.tsx' '*.stories.ts')

declare -a stories_to_verify=()
while IFS= read -r story_file; do
    [ -n "$story_file" ] || continue
    if [ ! -f "$story_file" ]; then
        echo "Skipping $story_file (deleted)"
        continue
    fi
    if is_served_story_file "$story_file"; then
        stories_to_verify+=("$story_file")
    else
        echo "Skipping $story_file (not served by the main storybook app)"
    fi
done <<< "$changed_story_files"

if [ ${#stories_to_verify[@]} -eq 0 ]; then
    echo "No changed story files to verify"
    exit 0
fi

# Build one escaped path regex per story file.
# These are passed as separate positional Jest patterns (OR-matched) rather than a
# single `|`-joined regex: a literal `|` survives into a downstream shell layer
# (pnpm exec / test-storybook re-invoking jest) where it's parsed as a pipe, which
# breaks the command. Positional patterns also sidestep the jest 30 rename of
# `--testPathPattern` to `--testPathPatterns`.
declare -a pattern_args=()
set_patterns() {
    pattern_args=()
    local story
    for story in "$@"; do
        pattern_args+=("$(echo "$story" | sed 's/\./\\./g')")
    done
}

# Returns non-zero when the run fails, so callers decide whether that blocks.
run_stories() {
    local browser="$1" run_name="$2" snapshot_flag="$3"
    echo "=== $run_name ==="

    # Run test-storybook directly (tests a pre-built storybook dist served over http-server).
    # pipefail is set at script level so tee preserves the exit code.
    # --passWithNoTests: changed stories may live in a separate storybook that
    # the main runner's testMatch doesn't cover. Those are verified by their own
    # CI, so finding no matching tests here is not a failure.
    # Keep STORYBOOK_SKIP_TAGS in sync with the visual-regression shards in ci-storybook.yml.
    local status=0
    STORYBOOK_SKIP_TAGS="test-skip,test-skip-${browser}" \
        pnpm --filter=@posthog/storybook exec test-storybook \
        "$snapshot_flag" --no-index-json --maxWorkers=1 \
        --browsers "$browser" \
        -- "${pattern_args[@]}" --passWithNoTests 2>&1 | tee "/tmp/storybook-verify-${run_name}.log" || status=$?
    if [ "$status" -eq 0 ]; then
        echo "$run_name passed"
    else
        echo "$run_name failed"
    fi
    echo ""
    return "$status"
}

declare -a failed_runs=()

if [ ${#stories_to_verify[@]} -gt 0 ]; then
    # Scale repeats down for large story sets so the job fits its time budget
    # (every run is single-worker, and only the repeats overlap). Small PRs keep full
    # verification;
    # mass refactors degrade to fewer passes instead of timing out.
    file_count=${#stories_to_verify[@]}
    if [ "$file_count" -gt 30 ] && [ "$REPEAT_COUNT" -gt 1 ]; then
        echo "NOTE: $file_count story files changed — reducing repeat count from $REPEAT_COUNT to 1 to fit the job time budget"
        REPEAT_COUNT=1
    elif [ "$file_count" -gt 10 ] && [ "$REPEAT_COUNT" -gt 2 ]; then
        echo "NOTE: $file_count story files changed — reducing repeat count from $REPEAT_COUNT to 2 to fit the job time budget"
        REPEAT_COUNT=2
    fi

    echo "Verifying $file_count changed file(s): 1 chromium baseline run, $((REPEAT_COUNT - 1)) concurrent chromium repeat(s), and 1 concurrent webkit run:"
    printf "  %s\n" "${stories_to_verify[@]}"
    set_patterns "${stories_to_verify[@]}"
    echo ""
    echo "testPathPatterns: ${pattern_args[*]}"
    echo ""

    # Each run does a full snapshot comparison. If any run fails, the story is flaky.
    #
    # Concurrency: every run below is single-worker (`--maxWorkers=1`), so running two at
    # once uses a second core instead of waiting for the first. They used to run one after
    # another, which made the job's wall the sum of four passes. On run 45907972522 (two
    # changed story files) the passes took 46s for the baseline, 313s and 315s for the two
    # `--ci` repeats and 14s for webkit: 688s of test time where the wall only needed to be
    # the longest pass. Two orderings matter and are kept:
    #   - chromium run 1 writes the baselines (`--updateSnapshot`), so it still finishes
    #     before the `--ci` repeats that compare against them.
    #   - the webkit pass writes its own `--webkit`-suffixed snapshots (`customSnapshotIdentifier`
    #     in common/storybook/.storybook/test-runner.ts) and shares no file with chromium,
    #     so it overlaps both.
    # A backgrounded run writes its own log through the tee in run_stories and the log is
    # printed after its wait, so the job log keeps one block of jest output per pass rather
    # than two interleaved streams.
    declare -a BACKGROUND_PIDS=()

    start_run() { # browser, run_name, snapshot_flag
        run_stories "$1" "$2" "$3" > /dev/null 2>&1 &
        BACKGROUND_PIDS+=("$!:$2")
    }

    collect_runs() {
        local entry pid name status
        for entry in "${BACKGROUND_PIDS[@]}"; do
            pid="${entry%%:*}"
            name="${entry#*:}"
            status=0
            wait "$pid" || status=$?
            # Printed after the wait so a failure's diff output is in the log, in run order.
            echo "=== $name (output) ==="
            cat "/tmp/storybook-verify-${name}.log" 2>/dev/null || true
            if [ "$status" -ne 0 ]; then
                failed_runs+=("$name")
            fi
        done
    }

    # webkit first, so it overlaps both the baseline run and the chromium repeats.
    # PR matrices render chromium only, so this pass exists for the webkit shards that
    # run nightly; `--updateSnapshot` stops a missing baseline from failing it.
    start_run webkit webkit-run --updateSnapshot

    # First run writes baselines for new stories (`--updateSnapshot`).
    run_stories chromium chromium-run-1 --updateSnapshot || failed_runs+=("chromium-run-1")

    # Repeats verify the snapshot is stable (`--ci`). They read the baselines the first
    # run just wrote and write nothing themselves, so they can run at the same time.
    if [ "$REPEAT_COUNT" -gt 1 ]; then
        for run in $(seq 2 "$REPEAT_COUNT"); do
            start_run chromium "chromium-run-$run" --ci
        done
    fi

    collect_runs
fi

if [ "${#failed_runs[@]}" -gt 0 ]; then
    echo "Flake verification failed in: ${failed_runs[*]}. Fix the stories before merging."
    exit 1
fi

echo "Flake verification passed"
