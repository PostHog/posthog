#!/bin/bash

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# hogli needs click, bin/ruff.sh needs ruff (no flox in sandbox)
# Use python -m pip so packages install into the same interpreter bin/ruff.sh uses
python -m pip install click ruff 2>/dev/null
# Root-only install: linting tools + husky, skips full workspace
pnpm install --frozen-lockfile --filter=. 2>/dev/null

exit 0
