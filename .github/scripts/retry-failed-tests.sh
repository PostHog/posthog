#!/usr/bin/env bash
# Rerun only the tests that failed in a CI test step, inside the same job.
#
# Reads the JUnit report(s) the first run wrote, then runs COMMAND with
#   FAILED_TEST_FILES  the <testsuite name> of every suite with a failure or error
#                      (the test file path where the reporter names suites by file)
#   FAILED_REPORTS     the first-run report files that contain a failure or error
# The retry is a separate report so Trunk still sees the first-run failure as
# raw flake signal. Exits 1, without running COMMAND, when there is nothing to
# retry or too much failed for a rerun to be a flake check; exits 1 after
# COMMAND when it ran no tests, so a caller can fall back to the first outcome.
set -euo pipefail

if [ "$#" -lt 4 ] || [ "$3" != "--" ]; then
    echo "usage: $0 FIRST_JUNIT_GLOB RETRY_JUNIT_GLOB -- COMMAND [ARGS...]" >&2
    exit 2
fi

first_glob="$1"
retry_glob="$2"
shift 3
max_failed_tests="${RETRY_MAX_FAILED_TESTS:-50}"

shopt -s nullglob
# shellcheck disable=SC2206 # the globs are meant to expand
first_reports=($first_glob)

count_failed_tests() {
    { cat "$@" | grep -oE '<(failure|error)([[:space:]/>])' || true; } | wc -l | tr -d ' '
}

failed_suite_names() {
    { tr '\n' ' ' <"$1" | grep -oE '<testsuite[[:space:]][^>]*>' | grep -E '(failures|errors)="[1-9]' || true; } |
        sed -E 's/.*[[:space:]]name="([^"]*)".*/\1/'
}

if [ "${#first_reports[@]}" -eq 0 ]; then
    echo "::notice::No JUnit report matches $first_glob, nothing to retry"
    exit 1
fi

failed_tests="$(count_failed_tests "${first_reports[@]}")"
if [ "$failed_tests" -eq 0 ]; then
    echo "::notice::No failed tests in ${first_reports[*]}, nothing to retry"
    exit 1
fi
if [ "$failed_tests" -gt "$max_failed_tests" ]; then
    echo "::notice::$failed_tests tests failed, more than RETRY_MAX_FAILED_TESTS=$max_failed_tests; not retrying"
    exit 1
fi

failed_reports=()
failed_files=()
for report in "${first_reports[@]}"; do
    if [ "$(count_failed_tests "$report")" -gt 0 ]; then
        failed_reports+=("$report")
        while IFS= read -r suite_name; do
            [ -n "$suite_name" ] && failed_files+=("$suite_name")
        done < <(failed_suite_names "$report")
    fi
done
FAILED_REPORTS="${failed_reports[*]}"
FAILED_TEST_FILES="$(printf '%s\n' "${failed_files[@]}" | sort -u | tr '\n' ' ' | sed 's/ $//')"
export FAILED_REPORTS FAILED_TEST_FILES

echo "Retrying $failed_tests failed tests from: $FAILED_TEST_FILES"
set +e
"$@"
status=$?
set -e

# shellcheck disable=SC2206 # the globs are meant to expand
retry_reports=($retry_glob)
if [ "${#retry_reports[@]}" -eq 0 ]; then
    echo "::warning::The retry wrote no JUnit report matching $retry_glob"
    exit 1
fi
if ! grep -q '<testcase' "${retry_reports[@]}"; then
    echo "::warning::The retry ran no tests"
    exit 1
fi
exit "$status"
