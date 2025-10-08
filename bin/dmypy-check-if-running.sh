#!/bin/bash
# Only run mypy if daemon is running, otherwise skip silently
# This allows developers to opt-in to mypy pre-commit checks by starting the daemon

if dmypy status &>/dev/null; then
    # Daemon is running - check with timeout to handle cold cache
    # Use timeout to avoid blocking commits on first check (cold cache)
    dmypy_output=$(timeout 0.5s dmypy check "$@" 2>&1 || true)

    # If timeout occurred, skip silently (cache is warming, CI will catch issues)
    if [ $? -eq 124 ]; then
        exit 0
    fi

    # Apply baseline filter
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
else
    # Daemon not running - skip silently
    # (daemon auto-starts with mprocs, so this is rare)
    exit 0
fi
