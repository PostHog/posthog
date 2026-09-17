#!/bin/bash
# Claude Code starts a language server with no working directory contract, so the
# root is searched for instead of assumed.
posthog_repo_root() {
    local candidate
    for candidate in "${CLAUDE_PROJECT_DIR:-}" "${CLAUDE_PLUGIN_ROOT:-}" "$PWD"; do
        [ -n "$candidate" ] || continue
        candidate=$(cd "$candidate" 2>/dev/null && pwd -P) || continue
        while [ "$candidate" != "/" ]; do
            if [ -f "$candidate/pnpm-workspace.yaml" ] && [ -f "$candidate/pyproject.toml" ]; then
                printf '%s\n' "$candidate"
                return 0
            fi
            candidate=$(dirname "$candidate")
        done
    done
    return 1
}
