#!/bin/bash
# SessionStart hook: make lint and test commands runnable in Claude Code on the web.

if [ "$CLAUDE_CODE_REMOTE" != "true" ]; then
    exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$PROJECT_DIR" || exit 0

# Install correct tool versions (uv, Python, Node, pnpm) if needed
if [ -x .claude/hooks/install-tool-versions.sh ]; then
    .claude/hooks/install-tool-versions.sh
fi

# install-tool-versions.sh runs in a subprocess so its PATH export doesn't propagate here;
# re-apply it explicitly so pnpm below sees the right node.
NODE_MAJOR=$(tr -d 'v[:space:]' < .nvmrc 2>/dev/null | cut -d. -f1)
if [ -n "$NODE_MAJOR" ] && [ -d "/opt/node${NODE_MAJOR}/bin" ]; then
    export PATH="/opt/node${NODE_MAJOR}/bin:$PATH"
fi

# Sync Python dependencies (installs django, pytest, ruff, etc. from pyproject.toml).
# --quiet drops the per-package list, which is hundreds of lines on a cold container.
# Errors stay visible: a failed sync leaves every Python test and linter unusable.
uv sync --quiet || echo "Warning: uv sync failed, Python tests and linters are unavailable" >&2

# '.' carries the shared JS tooling (oxlint, oxfmt, stylelint, tsgo) and husky.
# '@posthog/frontend...' adds the frontend and the product packages it depends on,
# which is what jest needs to collect and run the suite.
# The nodejs/ (plugin-server) workspace stays out on purpose: it pulls uWebSockets.js
# from codeload.github.com, which the sandbox egress policy blocks.
pnpm install --frozen-lockfile --prefer-offline --filter=. --filter=@posthog/frontend... || \
    echo "Warning: pnpm install failed, frontend tests and linters are unavailable" >&2

# Put the project venv ahead of the sandbox's unrelated global python tools, so
# 'pytest', 'ruff' and 'mypy' resolve to the versions pinned by pyproject.toml.
if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -d "$PROJECT_DIR/.venv/bin" ]; then
    {
        echo "export VIRTUAL_ENV=\"$PROJECT_DIR/.venv\""
        echo "export PATH=\"$PROJECT_DIR/.venv/bin:\$PATH\""
    } >> "$CLAUDE_ENV_FILE"
fi

exit 0
