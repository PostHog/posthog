#!/bin/bash
set -e

# Verify new backend snapshots for flakiness by running tests 3 times
# Fails if any new snapshot is inconsistent across runs

echo "🔍 Checking for new snapshot files..."

# Find all new (untracked) .ambr files
new_snapshots=$(git ls-files --others --exclude-standard '*.ambr' || true)

if [ -z "$new_snapshots" ]; then
    echo "✅ No new snapshots found, skipping verification"
    exit 0
fi

echo "📋 Found new snapshots:"
echo "$new_snapshots"
echo ""

# Extract test names from .ambr files
# Format: "# name: test_function_name" or "# name: TestClass.test_method_name"
declare -A test_files
declare -A test_names

while IFS= read -r ambr_file; do
    # Get the test file path (remove __snapshots__/filename.ambr, add test_ prefix)
    dir=$(dirname "$ambr_file")
    test_dir=$(dirname "$dir")
    basename=$(basename "$ambr_file" .ambr)

    # Try to find corresponding test file
    if [ -f "${test_dir}/${basename}.py" ]; then
        test_file="${test_dir}/${basename}.py"
    elif [ -f "${test_dir}/test_${basename}.py" ]; then
        test_file="${test_dir}/test_${basename}.py"
    else
        echo "⚠️  Warning: Could not find test file for ${ambr_file}, skipping"
        continue
    fi

    # Extract all test names from this ambr file
    names=$(grep '^# name:' "$ambr_file" | sed 's/^# name: //' || true)

    if [ -z "$names" ]; then
        echo "⚠️  Warning: No test names found in ${ambr_file}, skipping"
        continue
    fi

    # Store test names for this file
    while IFS= read -r name; do
        test_files["$name"]="$test_file"
        test_names["$name"]="$name"
    done <<< "$names"
done <<< "$new_snapshots"

if [ ${#test_files[@]} -eq 0 ]; then
    echo "❌ No test names could be extracted from new snapshots"
    exit 1
fi

echo "🧪 Found ${#test_files[@]} test(s) to verify"
echo ""

# Create temp directory for checksums
temp_dir=$(mktemp -d)
trap "rm -rf $temp_dir" EXIT

# Function to run test and capture snapshot checksum
run_test_and_checksum() {
    local test_file=$1
    local test_name=$2
    local run_number=$3

    # Convert test name format to pytest format
    # "TestClass.test_method" -> "TestClass::test_method"
    # "test_function" -> "test_function"
    pytest_name=$(echo "$test_name" | sed 's/\./::/')

    echo "  Run $run_number: pytest $test_file::$pytest_name"

    # Run the test with snapshot update
    if ! pytest "$test_file::$pytest_name" --snapshot-update -v 2>&1 | grep -E "(PASSED|FAILED)"; then
        echo "    ❌ Test failed"
        return 1
    fi

    # Calculate checksums of all new .ambr files
    while IFS= read -r ambr_file; do
        if [ -f "$ambr_file" ]; then
            sha256sum "$ambr_file" >> "$temp_dir/checksums_run${run_number}.txt"
        fi
    done <<< "$new_snapshots"

    return 0
}

# Run each test 3 times and verify consistency
failed_tests=()

for test_name in "${!test_files[@]}"; do
    test_file="${test_files[$test_name]}"

    echo "🔄 Verifying: $test_name (in $test_file)"

    # Clear previous checksums
    rm -f "$temp_dir"/checksums_run*.txt

    # Run 3 times
    for run in 1 2 3; do
        # Remove the ambr files before each run to force regeneration
        while IFS= read -r ambr_file; do
            rm -f "$ambr_file"
        done <<< "$new_snapshots"

        if ! run_test_and_checksum "$test_file" "$test_name" "$run"; then
            echo "  ❌ Test execution failed on run $run"
            failed_tests+=("$test_name (execution failed)")
            break
        fi
    done

    # Compare checksums across runs if all runs succeeded
    if [ -f "$temp_dir/checksums_run1.txt" ] && \
       [ -f "$temp_dir/checksums_run2.txt" ] && \
       [ -f "$temp_dir/checksums_run3.txt" ]; then

        # Sort checksum files for comparison
        sort "$temp_dir/checksums_run1.txt" > "$temp_dir/sorted1.txt"
        sort "$temp_dir/checksums_run2.txt" > "$temp_dir/sorted2.txt"
        sort "$temp_dir/checksums_run3.txt" > "$temp_dir/sorted3.txt"

        if ! diff -q "$temp_dir/sorted1.txt" "$temp_dir/sorted2.txt" > /dev/null 2>&1; then
            echo "  ❌ Snapshots differ between run 1 and 2"
            diff "$temp_dir/sorted1.txt" "$temp_dir/sorted2.txt" || true
            failed_tests+=("$test_name (flaky: run 1 vs 2)")
        elif ! diff -q "$temp_dir/sorted2.txt" "$temp_dir/sorted3.txt" > /dev/null 2>&1; then
            echo "  ❌ Snapshots differ between run 2 and 3"
            diff "$temp_dir/sorted2.txt" "$temp_dir/sorted3.txt" || true
            failed_tests+=("$test_name (flaky: run 2 vs 3)")
        else
            echo "  ✅ Snapshots consistent across all 3 runs"
        fi
    fi

    echo ""
done

# Report results
if [ ${#failed_tests[@]} -gt 0 ]; then
    echo "❌ VERIFICATION FAILED"
    echo ""
    echo "The following tests produced inconsistent snapshots:"
    for test in "${failed_tests[@]}"; do
        echo "  - $test"
    done
    echo ""
    echo "These tests are flaky and must be fixed before their snapshots can be committed."
    echo "Run the tests locally multiple times to reproduce and fix the non-determinism."
    exit 1
fi

echo "✅ All new snapshots verified successfully"
exit 0
