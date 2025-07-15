#!/bin/bash
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    elif [ -d "env" ]; then
        source env/bin/activate
    elif [ -d ".flox/env" ]; then
        source .flox/cache/venv/bin/activate
    fi
fi

python -m ruff "$@" 
