#!/bin/bash
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -d ".flox/env" ]; then
        source .flox/cache/venv/bin/activate
    elif [ -d ".venv" ]; then
        source .venv/bin/activate
    elif [ -d "env" ]; then
        source env/bin/activate
    fi
fi

python -m ruff "$@" 
