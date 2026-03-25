#!/bin/bash
set -euo pipefail

# update-content.sh — Runs on content changes (branch switch, git pull).
# Incremental dependency sync only.

echo "=== PostHog devbox: update-content ==="
cd /workspaces/posthog

uv sync
export COREPACK_ENABLE_AUTO_PIN=0
pnpm install --frozen-lockfile

# Regenerate process manager config if it exists
if [ -f bin/hogli ]; then
    uv run bin/hogli dev:generate 2>/dev/null || true
fi

echo "=== Update complete ==="
