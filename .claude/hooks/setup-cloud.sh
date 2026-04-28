#!/bin/bash

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Install correct tool versions (uv, Python, Node, pnpm) if needed
if [ -x .claude/hooks/install-tool-versions.sh ]; then
    .claude/hooks/install-tool-versions.sh
fi

# install-tool-versions.sh runs in a subprocess so its PATH export doesn't propagate here;
# re-apply it explicitly so pnpm below sees the right node.
NODE_MAJOR=$(cat .nvmrc 2>/dev/null | tr -d 'v[:space:]' | cut -d. -f1)
if [ -n "$NODE_MAJOR" ] && [ -d "/opt/node${NODE_MAJOR}/bin" ]; then
    export PATH="/opt/node${NODE_MAJOR}/bin:$PATH"
fi

# Sync Python dependencies (installs click, ruff, etc. from pyproject.toml)
uv sync 2>/dev/null
# Root-only install: linting tools + husky, skips full workspace
pnpm install --frozen-lockfile --filter=. 2>/dev/null

exit 0
