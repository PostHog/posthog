#!/bin/bash
set -e

# List of test files to skip the compiledjs tests
SKIP_COMPILEDJS_FILES=("")

# Files on which we only want to run Node.js tests
ONLY_NODEJS_FILES=("sql.hog")

# Navigate to the script's directory
cd "$(dirname "$0")"

# Build the project
cd typescript
pnpm run build
cd ..

# Navigate to the project root (parent of 'common/hogvm')
cd ../..

# Function to compute the basename for a given file
get_basename() {
    local file="$1"
    local base="${file%.hog}"
    base="${base##*/}"
    echo "common/hogvm/__tests__/__snapshots__/$base"
}

# Function to check if a value is in an array
is_in_array() {
    local val="$1"
    shift
    local arr=("$@")
    for item in "${arr[@]}"; do
        if [ "$item" == "$val" ]; then
            return 0
        fi
    done
    return 1
}

# Collect test files based on optional argument
if [ "$#" -eq 1 ]; then
    test_file="$1"
    # Adjust the test file path if it doesn't start with 'common/hogvm/'
    if [[ ! "$test_file" == common/hogvm/* ]]; then
        test_file="common/hogvm/__tests__/$test_file"
    fi
    # Check if the test file exists
    if [ ! -f "$test_file" ]; then
        echo "Test file $test_file does not exist."
        exit 1
    fi
    test_files=("$test_file")
    # Remove previous outputs for this test file only
    basename=$(get_basename "$test_file")
    rm -f "$basename.stdout.nodejs" "$basename.stdout.python" "$basename.stdout.compiledjs"
else
    shopt -s nullglob
    test_files=(common/hogvm/__tests__/*.hog)
    shopt -u nullglob

    if [ ${#test_files[@]} -eq 0 ]; then
        echo "No test files found in common/hogvm/__tests__/"
        exit 1
    fi

    # Remove all previous outputs
    rm -f common/hogvm/__tests__/__snapshots__/*.stdout.nodejs
    rm -f common/hogvm/__tests__/__snapshots__/*.stdout.python
    rm -f common/hogvm/__tests__/__snapshots__/*.stdout.compiledjs
fi

for file in "${test_files[@]}"; do
    echo "Testing $file"

    basename=$(get_basename "$file")
    filename=$(basename "$file")

    # Compile to .hoge
    ./bin/hoge "$file" "$basename.hoge"

    # Always run Node.js test
    ./bin/hog --nodejs "$basename.hoge" > "$basename.stdout.nodejs"

    # If this file is in ONLY_NODEJS_FILES, skip python + compiledjs
    if is_in_array "$filename" "${ONLY_NODEJS_FILES[@]}"; then
        mv "$basename.stdout.nodejs" "$basename.stdout"
        echo "Test passed (only nodejs tested)."
        continue
    fi

    # Otherwise, run Python
    ./bin/hog --python "$basename.hoge" > "$basename.stdout.python"

    # Check if compiledjs is skipped
    if is_in_array "$filename" "${SKIP_COMPILEDJS_FILES[@]}"; then
        echo "Skipping compiledjs tests for $filename"
        set +e
        diff "$basename.stdout.nodejs" "$basename.stdout.python"
        if [ $? -eq 0 ]; then
            mv "$basename.stdout.nodejs" "$basename.stdout"
            rm "$basename.stdout.python"
            echo "Test passed"
        else
            echo "Test failed: Output differs between Node.js and Python interpreters."
        fi
        set -e
    else
        # Run compiledjs
        set +e
        ./bin/hoge "$file" "$basename.js"
        node "$basename.js" > "$basename.stdout.compiledjs" 2>&1
        set -e

        # Compare outputs
        set +e
        diff "$basename.stdout.nodejs" "$basename.stdout.compiledjs"
        if [ $? -eq 0 ]; then
            diff "$basename.stdout.nodejs" "$basename.stdout.python"
            if [ $? -eq 0 ]; then
                mv "$basename.stdout.nodejs" "$basename.stdout"
                rm "$basename.stdout.python"
                rm "$basename.stdout.compiledjs"
                echo "Test passed"
            else
                echo "Test failed: Output differs between Node.js and Python interpreters."
            fi
        else
            echo "Test failed: Output differs between Node.js interpreter and compiled JavaScript."
        fi
        set -e
    fi
done
