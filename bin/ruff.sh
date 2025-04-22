#!/bin/bash
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -x ".venv/bin/ruff" ]; then
        exec .venv/bin/ruff "$@"
    elif [ -x "env/bin/ruff" ]; then
        exec env/bin/ruff "$@"
    elif [ -x ".flox/cache/venv/bin/ruff" ]; then
        exec .flox/cache/venv/bin/ruff "$@"
    fi
else
    exec ruff "$@"
fi
