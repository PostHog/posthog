#!/bin/bash
# Resolve the interpreter from VIRTUAL_ENV rather than trusting PATH: git hooks /
# lint-staged can run with VIRTUAL_ENV set but the venv not first on PATH, in which
# case a bare `python` picks up a system interpreter that has no ruff installed.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_CMD="python"

if [ -z "${VIRTUAL_ENV:-}" ]; then
    for venv in "$REPO_ROOT/.flox/cache/venv" "$REPO_ROOT/.venv" "$REPO_ROOT/env"; do
        if [ -d "$venv" ]; then
            source "$venv/bin/activate"
            PYTHON_CMD="$venv/bin/python"
            break
        fi
    done
else
    PYTHON_CMD="$VIRTUAL_ENV/bin/python"
fi

exec "$PYTHON_CMD" -m ruff "$@"
