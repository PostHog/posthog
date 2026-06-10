#!/bin/bash
set -euo pipefail

# Verify changed Playwright test files are stable by re-running them with --repeat-each.
# Catches flaky tests before they land — covers new files, unskipped tests, and any other modifications.
#
# Usage:
#   verify-playwright-new-tests-and-snapshots.sh <base_sha> [repeat_count]
#
# Example:
#   .github/scripts/verify-playwright-new-tests-and-snapshots.sh origin/master 10

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <base_sha> [repeat_count]" >&2
    exit 1
fi

BASE_SHA="$1"
REPEAT_COUNT="${2:-10}"

if ! [[ "$REPEAT_COUNT" =~ ^[0-9]+$ ]] || [ "$REPEAT_COUNT" -lt 1 ]; then
    echo "Error: repeat_count must be a positive integer" >&2
    exit 1
fi

echo "Detecting changed Playwright test files since $BASE_SHA..."

# Clean up stale results from a previous run (depot runners reuse workspaces).
RESULTS_FILE="playwright/flake-verification-results.json"
rm -f "$RESULTS_FILE"

# All spec files touched by the PR (added or modified). Playwright tests live in two
# places: cross-cutting tests under playwright/e2e/, and product-owned tests under
# products/*/frontend/e2e/. Both are picked up by playwright.config.ts.
#
# --diff-filter=AM excludes renames: a `git mv` (with at most a trivial import-path
# update) doesn't change test logic, so re-running it 10x for flake verification is
# noise. If a file is moved AND substantively edited in the same PR, the verifier
# won't catch it — but that's a rare pattern, and the alternative (re-verifying every
# moved test) blocks routine reorganizations.
changed_test_files=$(git diff --name-only --diff-filter=AM "$BASE_SHA..HEAD" -- 'playwright/**/*.spec.ts' 'products/*/frontend/e2e/**/*.spec.ts')

if [ -z "$changed_test_files" ]; then
    echo "No changed Playwright test files found — skipping flake verification"
    exit 0
fi
declare -a tests_to_run=()
while IFS= read -r test_file; do
    if [ ! -f "$test_file" ]; then
        echo "Warning: $test_file no longer exists (deleted in PR) — skipping"
        continue
    fi

    # Convert repo-relative paths to playwright-cwd-relative paths. The CI step runs
    # `pnpm --filter=@posthog/playwright exec playwright test`, which sets cwd to
    # playwright/, so files outside that directory need a `../` prefix.
    if [[ "$test_file" == playwright/* ]]; then
        tests_to_run+=("${test_file#playwright/}")
    else
        tests_to_run+=("../${test_file}")
    fi
done <<< "$changed_test_files"

if [ ${#tests_to_run[@]} -eq 0 ]; then
    echo "No runnable Playwright test files to verify"
    exit 0
fi

# Verification runs serially (--workers=1), so total work is files × repeat. Wide
# mechanical refactors can touch dozens of spec files; repeating each 10x would blow
# past the job's 45-minute timeout. Scale the repeat count down to fit a file-run
# budget, and below MIN_REPEAT repetitions there's no flake signal left — skip.
MAX_TOTAL_FILE_RUNS=60
MIN_REPEAT=2

num_files=${#tests_to_run[@]}
if ((num_files * REPEAT_COUNT > MAX_TOTAL_FILE_RUNS)); then
    scaled_repeat=$((MAX_TOTAL_FILE_RUNS / num_files))
    if ((scaled_repeat < MIN_REPEAT)); then
        echo "Skipping flake verification: $num_files changed spec files exceed the time budget even at --repeat-each=$MIN_REPEAT (likely a broad mechanical refactor)"
        exit 0
    fi
    echo "Scaling --repeat-each from $REPEAT_COUNT to $scaled_repeat: $num_files changed spec files exceed the $MAX_TOTAL_FILE_RUNS file-run budget"
    REPEAT_COUNT=$scaled_repeat
fi

echo "Verifying ${#tests_to_run[@]} file(s) with --repeat-each=$REPEAT_COUNT:"
printf "  %s\n" "${tests_to_run[@]}"

# Write a JSON results file for the PR comment step to pick up.
write_results() {
    local status="$1"
    local message="$2"
    local files_json
    files_json=$(printf '%s\n' "${tests_to_run[@]}" | jq -R . | jq -s .)
    jq -n \
        --arg status "$status" \
        --arg message "$message" \
        --argjson files "$files_json" \
        --argjson repeat "$REPEAT_COUNT" \
        '{status: $status, message: $message, files: $files, repeat_count: $repeat}' \
        > "$RESULTS_FILE"
}

set +e
# No --reporter override — uses playwright.config.ts reporters (html + json in CI).
# This overwrites the main run's report, which is fine: if verification fails,
# the verification report is the one that matters (the main tests passed).
# Fail fast once instability is detected so the job doesn't burn the full timeout
# on the remaining repeated runs.
pnpm --filter=@posthog/playwright exec playwright test "${tests_to_run[@]}" \
    --workers=1 --repeat-each="$REPEAT_COUNT" --retries=0 --max-failures=1
test_exit=$?
set -e

if [ "$test_exit" -ne 0 ]; then
    echo ""
    echo "Flake verification failed — one or more changed test files are unstable"
    write_results "failed" "Flake verification failed — changed tests are unstable across $REPEAT_COUNT repetitions"
    exit 1
fi

echo ""
echo "Flake verification passed — all changed test files stable across $REPEAT_COUNT repetitions"
write_results "passed" "All changed test files stable across $REPEAT_COUNT repetitions"
