#!/bin/bash
# Test script for bin/start --custom flag

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
START_SCRIPT="$SCRIPT_DIR/../start"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Test counter
TESTS_RUN=0
TESTS_PASSED=0

# Test function
run_test() {
    local test_name="$1"
    local expected_output="$2"
    shift 2
    local args=("$@")
    
    TESTS_RUN=$((TESTS_RUN + 1))
    
    # Capture output and exit code
    set +e
    output=$("$START_SCRIPT" "${args[@]}" 2>&1)
    exit_code=$?
    set -e
    
    if [[ "$output" == *"$expected_output"* ]]; then
        echo -e "${GREEN}✓${NC} $test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo -e "${RED}✗${NC} $test_name"
        echo "  Expected: $expected_output"
        echo "  Got: $output"
    fi
}

echo "Testing bin/start --custom flag..."
echo

# Test 1: --custom without path should error
run_test "Test --custom without path" \
    "Error: --custom requires a config path" \
    --custom

# Test 2: --custom with --minimal should error
run_test "Test --custom with --minimal conflicts" \
    "Error: Cannot use --custom with --minimal or --vite" \
    --custom test.yaml --minimal

# Test 3: --custom with --vite should error  
run_test "Test --custom with --vite conflicts" \
    "Error: Cannot use --custom with --minimal or --vite" \
    --custom test.yaml --vite

# Test 4: --custom with valid path (will fail at mprocs level, but that's expected)
# We're just checking it tries to run mprocs with the custom config
run_test "Test --custom with path attempts mprocs" \
    "Config file '/tmp/test-config.yaml' not found" \
    --custom /tmp/test-config.yaml

echo
echo "Tests completed: $TESTS_PASSED/$TESTS_RUN passed"

if [ $TESTS_PASSED -eq $TESTS_RUN ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed${NC}"
    exit 1
fi