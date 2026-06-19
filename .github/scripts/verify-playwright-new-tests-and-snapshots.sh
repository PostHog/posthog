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
#
# Diff from the merge-base, not the raw base tip. A two-dot "$BASE_SHA..HEAD" diff
# compares the two trees directly, so a PR branched off an older master inherits every
# spec file changed on master since the branch point — re-running dozens of unrelated
# tests serially blows past the job timeout. The merge-base is the branch point, so the
# diff yields only the PR's own changes. (Equivalent to three-dot "$BASE_SHA...HEAD",
# but computed explicitly so a too-shallow fetch degrades to a warning instead of a
# hard `git diff` failure under `set -e`.)
merge_base=$(git merge-base "$BASE_SHA" HEAD 2>/dev/null || true)
if [ -z "$merge_base" ]; then
    echo "Warning: no merge-base for $BASE_SHA and HEAD (shallow fetch too shallow?) — comparing against $BASE_SHA directly"
    merge_base="$BASE_SHA"
fi
changed_test_files=$(git diff --name-only --diff-filter=AM "$merge_base..HEAD" -- 'playwright/**/*.spec.ts' 'products/*/frontend/e2e/**/*.spec.ts')

# Also detect spec files affected by changed test helpers (page models, utils, fixtures).
# A page-model or utility change can introduce flakiness in every test that imports it.
# We resolve reverse dependencies AND do method-level targeting: only re-run tests that
# call the specific methods that changed, not every test in the consuming spec.
changed_helpers=$(git diff --name-only --diff-filter=AM "$merge_base..HEAD" -- \
    'playwright/**/*.ts' 'products/*/frontend/e2e/**/*.ts' \
    | grep -v '\.spec\.ts$' || true)

# Accumulate method names changed across all helpers. Tests calling any of these methods
# will be targeted for re-verification.
declare -a changed_method_names=()
# Track helpers where the change is in shared scope (constructor, fields, imports) —
# consuming specs of these helpers must run ALL their tests.
declare -a shared_scope_helpers=()

if [ -n "$changed_helpers" ]; then
    echo "Detecting spec files that import changed helpers..."
    # Regex for method/function declarations in TypeScript class-based page models.
    # Matches: `async goToList(`, `detailTable():`, `searchFor(query` etc.
    # Does NOT match: `constructor(`, class fields, or import lines.
    HELPER_METHOD_RE='^[[:space:]]*(async[[:space:]]+)?[a-zA-Z_][a-zA-Z0-9_]*[[:space:]]*\('

    while IFS= read -r helper; do
        [ -z "$helper" ] && continue
        helper_basename=$(basename "$helper" .ts)

        # Find spec files that import this helper (anchored to import/require patterns)
        consuming=$(grep -Erl --include='*.spec.ts' "(from|require).*['\"/]${helper_basename}['\"]" \
            playwright/e2e/ products/*/frontend/e2e/ 2>/dev/null || true)
        [ -z "$consuming" ] && continue

        num_consuming=$(echo "$consuming" | wc -l | tr -d ' ')
        echo "  $helper → $num_consuming consuming spec(s)"

        # Determine which methods changed in this helper (same hunk-mapping as spec targeting).
        if [ ! -f "$helper" ]; then
            echo "    Warning: $helper no longer exists — skipping"
            continue
        fi

        # Method declaration line numbers (exclude constructor — that's shared scope).
        mapfile -t method_lines < <(grep -nE "$HELPER_METHOD_RE" "$helper" | grep -v 'constructor' | cut -d: -f1)
        total_methods=${#method_lines[@]}

        # Changed line numbers in the helper.
        mapfile -t helper_changed_lines < <(
            git diff -U0 "$merge_base..HEAD" -- "$helper" \
                | sed -nE 's/^@@ -[0-9]+(,[0-9]+)? \+([0-9]+)(,([0-9]+))? @@.*/\2 \4/p' \
                | while read -r start count; do
                    count=${count:-1}
                    ((count == 0)) && count=1
                    for ((i = 0; i < count; i++)); do echo $((start + i)); done
                done
        )

        # If no methods detected or no changed lines, treat as shared-scope (whole file).
        if ((total_methods == 0)) || ((${#helper_changed_lines[@]} == 0)); then
            shared_scope_helpers+=("$helper")
            # Add all consuming specs to changed_test_files (will run whole file later)
            changed_test_files=$(printf '%s\n%s' "$changed_test_files" "$consuming" | sort -u | sed '/^$/d')
            echo "    → no method boundaries detected — whole-file fallback for consumers"
            continue
        fi

        first_method_line=${method_lines[0]}
        helper_shared_scope=0
        declare -A hit_method_lines=()

        for cl in "${helper_changed_lines[@]}"; do
            # Change above first method → shared scope (imports, constructor, class fields).
            if ((cl < first_method_line)); then
                helper_shared_scope=1
                break
            fi
            # Find the enclosing method.
            enclosing=$first_method_line
            for ml in "${method_lines[@]}"; do
                ((ml <= cl)) && enclosing=$ml || break
            done
            hit_method_lines[$enclosing]=1
        done

        if ((helper_shared_scope)); then
            shared_scope_helpers+=("$helper")
            changed_test_files=$(printf '%s\n%s' "$changed_test_files" "$consuming" | sort -u | sed '/^$/d')
            echo "    → change in shared scope (constructor/fields/imports) — whole-file fallback"
            continue
        fi

        # Extract the actual method names from the hit lines.
        for ml in "${!hit_method_lines[@]}"; do
            method_name=$(sed -n "${ml}p" "$helper" | sed -E 's/^[[:space:]]*(async[[:space:]]+)?([a-zA-Z_][a-zA-Z0-9_]*)[[:space:]]*\(.*/\2/')
            if [ -n "$method_name" ]; then
                changed_method_names+=("$method_name")
                echo "    → changed method: $method_name"
            fi
        done
        unset hit_method_lines

        # Add consuming specs to changed_test_files — the targeting loop below will narrow
        # to specific tests that call the changed methods.
        changed_test_files=$(printf '%s\n%s' "$changed_test_files" "$consuming" | sort -u | sed '/^$/d')
    done <<< "$changed_helpers"
fi

if [ -z "$changed_test_files" ]; then
    echo "No changed Playwright test files found — skipping flake verification"
    exit 0
fi
# Top-level test declaration (test / test.skip / .only / .fixme / .fail). Used both to
# locate test boundaries and as a heuristic test count — it doesn't expand parameterized
# loops or test.describe fan-out, but it's good enough to target and budget the re-run.
TEST_DECL_RE='^[[:space:]]*test(\.(skip|fixme|only|fail))?\('

# Convert a repo-relative spec path to one relative to playwright/ (the CI step's cwd:
# `pnpm --filter=@posthog/playwright exec playwright test`). Files outside that dir need `../`.
playwright_path() {
    local f="$1"
    if [[ "$f" == playwright/* ]]; then
        printf '%s' "${f#playwright/}"
    else
        printf '%s' "../$f"
    fi
}

# Re-run only the tests that actually changed. We map the diff's changed line ranges onto
# the test() declarations in each file and target those tests by `file:line`. A change that
# lands outside any test body — imports, helpers, fixtures, before/after hooks, describe-level
# setup — can affect every test in the file, so we conservatively fall back to the whole file.
#
# For specs pulled in via helper method changes (no direct diff), we target only the tests
# that call the changed methods — avoiding a full-file re-run that would exceed the budget.
declare -a targets=()
num_targeted_tests=0
while IFS= read -r test_file; do
    [ -z "$test_file" ] && continue
    if [ ! -f "$test_file" ]; then
        echo "Warning: $test_file no longer exists (deleted in PR) — skipping"
        continue
    fi

    pw_file="$(playwright_path "$test_file")"

    # Test declaration line numbers in the new file (ascending — grep emits in file order).
    mapfile -t test_lines < <(grep -nE "$TEST_DECL_RE" "$test_file" | cut -d: -f1)
    total_file_tests=${#test_lines[@]}

    # Changed line numbers in the new file. -U0 keeps each hunk to just its changed lines;
    # parse the `@@ -a,b +c,d @@` headers for the new-side range c..c+d-1 (d defaults to 1;
    # d=0 is a pure deletion, mapped to the line it sat on so the enclosing test still re-runs).
    mapfile -t changed_lines < <(
        git diff -U0 "$merge_base..HEAD" -- "$test_file" \
            | sed -nE 's/^@@ -[0-9]+(,[0-9]+)? \+([0-9]+)(,([0-9]+))? @@.*/\2 \4/p' \
            | while read -r start count; do
                count=${count:-1}
                ((count == 0)) && count=1
                for ((i = 0; i < count; i++)); do echo $((start + i)); done
            done
    )

    # Spec has a direct diff — use existing line-based targeting.
    if ((${#changed_lines[@]} > 0)); then
        # Can't analyze (no detectable tests) → re-run the whole file.
        if ((total_file_tests == 0)); then
            targets+=("$pw_file")
            num_targeted_tests=$((num_targeted_tests + 1))
            continue
        fi

        first_test_line=${test_lines[0]}
        declare -A hit_test_lines=()
        shared_change=0
        for cl in "${changed_lines[@]}"; do
            # Above the first test → shared scope (imports / module helpers / top-of-describe hooks).
            if ((cl < first_test_line)); then
                shared_change=1
                break
            fi
            enclosing=$first_test_line
            for tl in "${test_lines[@]}"; do
                ((tl <= cl)) && enclosing=$tl || break
            done
            hit_test_lines[$enclosing]=1
        done

        # Shared-scope change, or every test touched → whole file (correctness over cleverness).
        if ((shared_change)) || ((${#hit_test_lines[@]} >= total_file_tests)); then
            ((shared_change)) && echo "  $test_file: change touches shared scope — re-running all $total_file_tests test(s)"
            targets+=("$pw_file")
            num_targeted_tests=$((num_targeted_tests + total_file_tests))
        else
            for tl in "${!hit_test_lines[@]}"; do
                targets+=("$pw_file:$tl")
            done
            num_targeted_tests=$((num_targeted_tests + ${#hit_test_lines[@]}))
            echo "  $test_file: re-running ${#hit_test_lines[@]} changed test(s) of $total_file_tests"
        fi
        unset hit_test_lines
        continue
    fi

    # No direct diff — this spec was pulled in via helper method changes.
    # Target only tests whose bodies reference the changed method names.
    if ((${#changed_method_names[@]} == 0)) || ((total_file_tests == 0)); then
        # No method names to match (shared-scope helper change) → whole file.
        targets+=("$pw_file")
        num_targeted_tests=$((num_targeted_tests + (total_file_tests > 0 ? total_file_tests : 1)))
        echo "  $test_file: helper shared-scope change — re-running all $total_file_tests test(s)"
        continue
    fi

    # Build a grep pattern for any of the changed method names (e.g. "goToList|searchFor").
    method_pattern=$(printf '%s\n' "${changed_method_names[@]}" | sort -u | paste -sd'|')

    # For each test, check if its body (from test declaration to next test or EOF) calls
    # any changed method.
    declare -A method_hit_tests=()
    for ((i = 0; i < ${#test_lines[@]}; i++)); do
        start_line=${test_lines[$i]}
        if ((i + 1 < ${#test_lines[@]})); then
            end_line=$((test_lines[$((i + 1))] - 1))
        else
            end_line=$(wc -l < "$test_file")
        fi
        # Check if this test body references any changed method.
        if sed -n "${start_line},${end_line}p" "$test_file" | grep -qE "$method_pattern"; then
            method_hit_tests[$start_line]=1
        fi
    done

    if ((${#method_hit_tests[@]} == 0)); then
        echo "  $test_file: no tests call changed methods — skipping"
    elif ((${#method_hit_tests[@]} >= total_file_tests)); then
        targets+=("$pw_file")
        num_targeted_tests=$((num_targeted_tests + total_file_tests))
        echo "  $test_file: all $total_file_tests test(s) call changed methods — re-running whole file"
    else
        for tl in "${!method_hit_tests[@]}"; do
            targets+=("$pw_file:$tl")
        done
        num_targeted_tests=$((num_targeted_tests + ${#method_hit_tests[@]}))
        echo "  $test_file: re-running ${#method_hit_tests[@]} test(s) of $total_file_tests that call changed methods"
    fi
    unset method_hit_tests
done <<< "$changed_test_files"

if [ ${#targets[@]} -eq 0 ]; then
    echo "No runnable Playwright tests to verify"
    exit 0
fi

# Verification runs serially (--workers=1) at the full --repeat-each, so total work is
# targeted_tests × repeat. Because we re-run only the changed tests, this stays small for a
# normal PR and keeps the full repeat. A genuinely broad change — dozens of edited tests, or
# a shared-scope edit in a large spec that forces a whole-file fallback — can still blow the
# job's 45-minute timeout. Rather than water down the repeat count (which destroys the flake
# signal), skip verification entirely. ~40 serial test-runs (~5 min) fits the slack left after
# the main suite.
MAX_TOTAL_TEST_RUNS=40
if ((num_targeted_tests * REPEAT_COUNT > MAX_TOTAL_TEST_RUNS)); then
    echo "Skipping flake verification: $num_targeted_tests targeted test(s) × --repeat-each=$REPEAT_COUNT exceeds the ~${MAX_TOTAL_TEST_RUNS}-run time budget (broad change or a shared-scope edit in a large spec)"
    exit 0
fi

echo "Verifying $num_targeted_tests test(s) with --repeat-each=$REPEAT_COUNT:"
printf "  %s\n" "${targets[@]}"

# Write a JSON results file for the PR comment step to pick up.
write_results() {
    local status="$1"
    local message="$2"
    local files_json
    files_json=$(printf '%s\n' "${targets[@]}" | jq -R . | jq -s .)
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
pnpm --filter=@posthog/playwright exec playwright test "${targets[@]}" \
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
