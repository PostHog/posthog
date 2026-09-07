#!/bin/bash
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "$VIRTUAL_ENV" ]; then
    source "$REPO_ROOT/bin/helpers/dev-env.sh"
    FOUND_VENV="$(posthog_find_venv "$REPO_ROOT")"
    if [ -n "$FOUND_VENV" ]; then
        source "$FOUND_VENV/bin/activate"
    fi
fi

python -m ruff "$@"
