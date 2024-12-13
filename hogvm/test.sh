#!/bin/bash
set -e

# List of test files to skip the compiledjs tests
SKIP_COMPILEDJS_FILES=("crypto.hog")

# Navigate to the script's directory
cd "$(dirname "$0")"

# Build the project
cd typescript
pnpm run build
cd ..

# Navigate to the project root (parent directory of 'hogvm')
cd ..

# Function to compute the basename for a given file
get_basename() {
    local file="$1"
    local base="${file%.hog}"
    base="${base##*/}"
    echo "hogvm/__tests__/__snapshots__/$base"
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

# Check if an argument is provided
if [ "$#" -eq 1 ]; then
    test_file="$1"
    # Adjust the test file path if it doesn't start with 'hogvm/'
    if [[ ! "$test_file" == hogvm/* ]]; then
        test_file="hogvm/__tests__/$test_file"
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
    test_files=(hogvm/__tests__/*.hog)
    shopt -u nullglob

    if [ ${#test_files[@]} -eq 0 ]; then
        echo "No test files found in hogvm/__tests__/"
        exit 1
    fi

    # Remove all previous outputs
    rm -f hogvm/__tests__/__snapshots__/*.stdout.nodejs
    rm -f hogvm/__tests__/__snapshots__/*.stdout.python
    rm -f hogvm/__tests__/__snapshots__/*.stdout.compiledjs
fi

for file in "${test_files[@]}"; do
    echo "Testing $file"

    basename=$(get_basename "$file")
    filename=$(basename "$file")

    ./bin/hoge "$file" "$basename.hoge"
    ./bin/hog --nodejs "$basename.hoge" > "$basename.stdout.nodejs"
    ./bin/hog --python "$basename.hoge" > "$basename.stdout.python"

    # Check if the current file should skip the compiledjs tests
    if is_in_array "$filename" "${SKIP_COMPILEDJS_FILES[@]}"; then
        # Skip compiledjs steps for this file
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
        # Proceed with compiledjs tests
        set +e
        ./bin/hoge "$file" "$basename.js"
        node "$basename.js" > "$basename.stdout.compiledjs" 2>&1
        set -e

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
