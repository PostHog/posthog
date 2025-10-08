#!/bin/bash
# Only run mypy if daemon is running, otherwise skip silently
# This allows developers to opt-in to mypy pre-commit checks by starting the daemon

if dmypy status &>/dev/null; then
    dmypy check "$@"
else
    # Daemon not running - skip silently (no error, no slowdown)
    exit 0
fi
