#!/bin/bash
if [ -z "$VIRTUAL_ENV" ]; then
    if [ -d ".flox/env" ]; then
        source .flox/cache/venv/bin/activate
    else
        source env/bin/activate
    fi
fi

python -m ruff "$@" 
