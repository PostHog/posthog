#!/bin/bash
# Fast type checking via dmypy daemon
# Only runs if daemon is available (started via mprocs or manually)
# If daemon is running, you opted into type checking, so we wait for results

# Check if daemon is running
if ! dmypy status &>/dev/null; then
    # No daemon - skip silently
    exit 0
fi

# Run check - no timeout since daemon running means you want type checking
dmypy_output=$(dmypy check "$@" 2>&1)

# Apply baseline filter to show only NEW errors
baseline_output=$(echo "$dmypy_output" | mypy-baseline filter 2>&1)

# Extract only error lines for the files being checked
# Convert absolute paths to relative paths for matching
rel_paths=$(echo "$@" | tr ' ' '\n' | sed "s|^$(pwd)/||" | tr '\n' '|' | sed 's/|$//')
filtered=$(echo "$baseline_output" | grep -E "^($rel_paths):[0-9]+:" || true)

# Show errors if any were found
if [ -n "$filtered" ]; then
    echo "$filtered"
    exit 1
fi

exit 0
