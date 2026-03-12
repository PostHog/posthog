#!/bin/bash

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# ── Install flox if not present ──────────────────────────────────────
if ! command -v flox &>/dev/null; then
    curl -fsSL https://install.flox.dev/deb | sudo bash 2>/dev/null
    sudo apt install -y flox 2>/dev/null
fi

# ── Fallback: ensure minimal tooling even if flox install fails ──────
# hogli needs click, bin/ruff.sh needs ruff
python3 -m pip install click ruff 2>/dev/null
# Root-only install: linting tools + husky, skips full workspace
pnpm install --frozen-lockfile --filter=. 2>/dev/null

exit 0
