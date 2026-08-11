#!/usr/bin/env bash
# Fails any PR that changes both products/desktop/** and backend code that
# ships in production (the Django image or a rust service): desktop releases
# auto-update users on their own schedule, with no orchestration against
# backend deploys, so a coupled PR can ship a client that calls endpoints that
# are not deployed yet.
set -euo pipefail

REPOSITORY="${REPOSITORY:?}"
PR_NUMBER="${PR_NUMBER:?}"

# Deploy-relevant subset of ci-backend.yml's `backend` filter (paths that ship
# in the Django image) plus rust/** (rust services deploy separately and also
# serve clients). Tooling/test entries (pyproject.toml, uv.lock, conftest.py,
# docker-compose*, ...) are deliberately excluded so they cannot block an
# unrelated desktop PR.
is_backend_path() {
    case "$1" in
        *.md | *.mdx) return 1 ;;
        products/desktop/*) return 1 ;;
        posthog/*) return 0 ;;
        rust/*) return 0 ;;
        ee/frontend/*) return 1 ;;
        ee/*) return 0 ;;
        common/__init__.py | common/hogql_parser/* | common/hogvm/* | common/ingestion/* | common/migration_utils/* | common/plugin_transpiler/*) return 0 ;;
        products/*/backend/* | products/*.py) return 0 ;;
        frontend/src/products.json) return 0 ;;
        *) return 1 ;;
    esac
}

is_desktop_path() {
    case "$1" in
        products/desktop/*) return 0 ;;
        *) return 1 ;;
    esac
}

# A GitHub API failure must fail the check rather than read as an empty file list.
fetch_api() {
    if ! gh api "$@"; then
        echo "::error::GitHub API request failed for $*; cannot verify desktop/backend separation" >&2
        return 1
    fi
}

touched_desktop=false
touched_backend=false
files=$(fetch_api --paginate "repos/$REPOSITORY/pulls/$PR_NUMBER/files" | jq -r '.[].filename') || exit 1
while IFS= read -r path; do
    [ -n "$path" ] || continue
    if is_desktop_path "$path"; then touched_desktop=true; fi
    if is_backend_path "$path"; then touched_backend=true; fi
done <<<"$files"

if [ "$touched_desktop" = false ]; then
    echo "No products/desktop changes; nothing to check."
    exit 0
fi

# Labels come from the API, not the event payload, so applying the skip label
# and re-running is enough; label changes do not retrigger pull_request runs.
pr_json=$(fetch_api "repos/$REPOSITORY/pulls/$PR_NUMBER") || exit 1
if jq -e '[.labels[]?.name] | index("skip-desktop-backend-check") != null' <<<"$pr_json" >/dev/null; then
    echo "::notice::PR #$PR_NUMBER carries skip-desktop-backend-check; skipping the coupling check."
    exit 0
fi

if [ "$touched_backend" = true ]; then
    echo "::error::This PR contains both products/desktop and backend changes. These must be separated into different PRs."
    echo ""
    echo "Why? Desktop releases auto-update users and are not orchestrated with backend"
    echo "deploys. If desktop code depends on a backend change in the same PR, a release"
    echo "can ship a client that calls endpoints that are not deployed yet."
    echo ""
    echo "Solution: split into two PRs:"
    echo "  1. First PR: backend changes only (merge and wait for the deploy)."
    echo "  2. Second PR: desktop changes (merge once the backend is live)."
    echo ""
    echo "If the two halves are independent (safe to ship in either order), apply the"
    echo "'skip-desktop-backend-check' label and re-run this check."
    exit 1
fi

echo "No desktop/backend coupling detected."
