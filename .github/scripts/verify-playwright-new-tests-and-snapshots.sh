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

# All spec files touched by the PR (added or modified).
changed_test_files=$(git diff --name-only "$BASE_SHA..HEAD" -- 'playwright/**/*.spec.ts')

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

    # Strip the playwright/ prefix — Playwright runs relative to its project root.
    tests_to_run+=("${test_file#playwright/}")
done <<< "$changed_test_files"

if [ ${#tests_to_run[@]} -eq 0 ]; then
    echo "No runnable Playwright test files to verify"
    exit 0
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
pnpm --filter=@posthog/playwright exec playwright test "${tests_to_run[@]}" \
    --workers=1 --repeat-each="$REPEAT_COUNT" --retries=0
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
