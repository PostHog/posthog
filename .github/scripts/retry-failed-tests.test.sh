#!/usr/bin/env bash
set -euo pipefail

script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/retry-failed-tests.sh"
workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

passing_suite='<testsuite name="src/pass.test.ts" tests="1" failures="0" errors="0"><testcase name="a" /></testsuite>'
failing_suite='<testsuite name="src/fail.test.ts" tests="2" failures="1" errors="0"><testcase name="a" /><testcase name="b"><failure message="boom">trace</failure></testcase></testsuite>'
erroring_suite='<testsuite errors="1" failures="0" name="src/error.test.ts" tests="1"><testcase name="a"><error message="import" /></testcase></testsuite>'
pytest_suite='<testsuite name="pytest" errors="0" failures="2" tests="3"><testcase classname="t" name="x" file="t.py"><failure message="x">t</failure></testcase><testcase classname="t" name="y" file="t.py"><failure message="y">t</failure></testcase><testcase classname="t" name="z" file="t.py" /></testsuite>'
retried_suite='<testsuite name="src/fail.test.ts" tests="1" failures="0"><testcase name="b" /></testsuite>'
empty_retry_suite='<testsuite name="pytest" tests="0" failures="0" />'

# The fake test command records what the helper handed it, then writes the retry
# report it was told to and exits with the code it was told to.
fake_command="$workdir/fake-test-command.sh"
cat >"$fake_command" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "${FAILED_TEST_FILES-unset}" >"$RECORD_DIR/failed-test-files"
printf '%s\n' "${FAILED_REPORTS-unset}" >"$RECORD_DIR/failed-reports"
printf '%s\n' "$*" >"$RECORD_DIR/args"
if [ -n "$RETRY_REPORT_BODY" ]; then
    printf '%s\n' "$RETRY_REPORT_BODY" >"$RETRY_REPORT_PATH"
fi
exit "$COMMAND_EXIT"
EOF
chmod +x "$fake_command"

# run_case NAME EXPECTED_STATUS EXPECTED_FAILED_FILES EXPECTED_FAILED_REPORTS RETRY_REPORT COMMAND_EXIT FIRST_REPORT...
# EXPECTED_FAILED_FILES 'not-run' asserts the command never ran.
run_case() {
    local name="$1" expected_status="$2" expected_files="$3" expected_reports="$4" retry_report="$5" command_exit="$6"
    shift 6
    local root="$workdir/$name" output status index=0 report
    mkdir -p "$root/reports"
    for report in "$@"; do
        if [ -n "$report" ]; then
            printf '%s\n' "$report" >"$root/reports/junit-$index.xml"
        fi
        index=$((index + 1))
    done

    set +e
    output=$(cd "$root" &&
        RECORD_DIR="$root" RETRY_REPORT_BODY="$retry_report" RETRY_REPORT_PATH="$root/reports/retry-junit-0.xml" COMMAND_EXIT="$command_exit" \
            bash "$script" 'reports/junit-*.xml' 'reports/retry-junit-*.xml' -- "$fake_command" --flag value 2>&1)
    status=$?
    set -e

    if [ "$status" -ne "$expected_status" ]; then
        echo "FAIL: $name returned $status, expected $expected_status"
        printf '%s\n' "$output"
        exit 1
    fi
    if [ "$expected_files" = "not-run" ]; then
        if [ -e "$root/args" ]; then
            echo "FAIL: $name ran the command"
            exit 1
        fi
        if ! grep -qE '::notice::.*(nothing to retry|not retrying)' <<<"$output"; then
            echo "FAIL: $name did not explain why it skipped the retry"
            printf '%s\n' "$output"
            exit 1
        fi
    else
        if [ "$(cat "$root/failed-test-files")" != "$expected_files" ]; then
            echo "FAIL: $name passed FAILED_TEST_FILES '$(cat "$root/failed-test-files")', expected '$expected_files'"
            exit 1
        fi
        if [ "$(cat "$root/failed-reports")" != "$expected_reports" ]; then
            echo "FAIL: $name passed FAILED_REPORTS '$(cat "$root/failed-reports")', expected '$expected_reports'"
            exit 1
        fi
        if [ "$(cat "$root/args")" != "--flag value" ]; then
            echo "FAIL: $name passed args '$(cat "$root/args")', expected '--flag value'"
            exit 1
        fi
    fi
    echo "ok: $name"
}

run_case no-first-report 1 not-run '' "$retried_suite" 0 ''
run_case nothing-failed 1 not-run '' "$retried_suite" 0 "$passing_suite"
run_case retry-passes 0 'src/fail.test.ts' 'reports/junit-0.xml' "$retried_suite" 0 "$failing_suite"
run_case retry-fails-again 1 'src/fail.test.ts' 'reports/junit-0.xml' "$failing_suite" 1 "$failing_suite"
run_case retry-exit-code-is-kept 7 'src/fail.test.ts' 'reports/junit-0.xml' "$retried_suite" 7 "$failing_suite"
run_case retry-wrote-no-report 1 'src/fail.test.ts' 'reports/junit-0.xml' '' 0 "$failing_suite"
run_case retry-ran-no-tests 1 'pytest' 'reports/junit-0.xml' "$empty_retry_suite" 0 "$pytest_suite"
run_case errors-count-as-failures 0 'src/error.test.ts' 'reports/junit-0.xml' "$retried_suite" 0 "$erroring_suite"
run_case failed-files-across-reports 0 'src/error.test.ts src/fail.test.ts' 'reports/junit-0.xml reports/junit-2.xml' "$retried_suite" 0 "$failing_suite" "$passing_suite" "$erroring_suite"
RETRY_MAX_FAILED_TESTS=1 run_case too-many-failures 1 not-run '' "$retried_suite" 0 "$pytest_suite"
RETRY_MAX_FAILED_TESTS=2 run_case failures-at-the-cap 0 'pytest' 'reports/junit-0.xml' "$retried_suite" 0 "$pytest_suite"

echo "Retry failed tests regression cases passed."
