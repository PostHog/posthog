#!/bin/bash
set -e

# Verify new backend snapshots for flakiness by running entire test files 3 times
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

# Extract unique test files from snapshot paths
# snapshot path: posthog/hogql/database/test/__snapshots__/test_database.ambr
# test path:     posthog/hogql/database/test/test_database.py
declare -A test_files

while IFS= read -r ambr_file; do
    # Get the test file path
    dir=$(dirname "$ambr_file")          # posthog/hogql/database/test/__snapshots__
    test_dir=$(dirname "$dir")            # posthog/hogql/database/test
    basename=$(basename "$ambr_file" .ambr)  # test_database

    # Construct test file path
    test_file="${test_dir}/${basename}.py"

    if [ -f "$test_file" ]; then
        test_files["$test_file"]=1
    else
        echo "⚠️  Warning: Could not find test file ${test_file} for ${ambr_file}"
    fi
done <<< "$new_snapshots"

if [ ${#test_files[@]} -eq 0 ]; then
    echo "❌ No test files could be found for new snapshots"
    exit 1
fi

echo "🧪 Found ${#test_files[@]} test file(s) with new snapshots"
echo ""

# Create temp directory for checksums
temp_dir=$(mktemp -d)
trap "rm -rf $temp_dir" EXIT

# Run each test file 3 times and verify consistency
failed_files=()

for test_file in "${!test_files[@]}"; do
    echo "🔄 Verifying all tests in: $test_file"

    # Clear previous checksums
    rm -f "$temp_dir"/checksums_run*.txt

    # Run 3 times
    for run in 1 2 3; do
        echo "  Run $run: pytest $test_file --snapshot-update"

        # Remove new snapshots before each run to force regeneration
        while IFS= read -r ambr_file; do
            rm -f "$ambr_file"
        done <<< "$new_snapshots"

        # Run the entire test file
        if ! pytest "$test_file" --snapshot-update -v 2>&1 | tail -3; then
            echo "  ❌ Test execution failed on run $run"
            failed_files+=("$test_file (execution failed)")
            break
        fi

        # Calculate checksums of all new .ambr files
        while IFS= read -r ambr_file; do
            if [ -f "$ambr_file" ]; then
                sha256sum "$ambr_file" >> "$temp_dir/checksums_run${run}.txt"
            fi
        done <<< "$new_snapshots"
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
            echo "  Diff:"
            diff "$temp_dir/sorted1.txt" "$temp_dir/sorted2.txt" | head -20 || true
            failed_files+=("$test_file (flaky: run 1 vs 2)")
        elif ! diff -q "$temp_dir/sorted2.txt" "$temp_dir/sorted3.txt" > /dev/null 2>&1; then
            echo "  ❌ Snapshots differ between run 2 and 3"
            echo "  Diff:"
            diff "$temp_dir/sorted2.txt" "$temp_dir/sorted3.txt" | head -20 || true
            failed_files+=("$test_file (flaky: run 2 vs 3)")
        else
            echo "  ✅ Snapshots consistent across all 3 runs"
        fi
    fi

    echo ""
done

# Report results
if [ ${#failed_files[@]} -gt 0 ]; then
    echo "❌ VERIFICATION FAILED"
    echo ""
    echo "The following test files produced inconsistent snapshots:"
    for file in "${failed_files[@]}"; do
        echo "  - $file"
    done
    echo ""
    echo "These tests contain flakiness and must be fixed before their snapshots can be committed."
    echo "Run the test file locally multiple times to reproduce and fix the non-determinism."
    exit 1
fi

echo "✅ All new snapshots verified successfully"
exit 0
