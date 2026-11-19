#!/usr/bin/env bash
# Fails any PR that changes both desktop code and a Rust service. Desktop and
# agent releases auto-update users, so a coupled PR can ship a client that
# calls endpoints that are not deployed yet.
#
# desktop-tag.yml and desktop-agent-tag.yml hold each release until prod-us
# and prod-eu run a Django build that contains the release commit, so Django
# changes may share a PR with desktop code. Rust services deploy separately
# and write no deployment record that the releases can wait for.
set -euo pipefail

REPOSITORY="${REPOSITORY:?}"
PR_NUMBER="${PR_NUMBER:?}"

# Docs cannot change what a deployed service serves, so they cannot block a desktop PR.
is_rust_path() {
    case "$1" in
        *.md | *.mdx) return 1 ;;
        rust/*) return 0 ;;
        *) return 1 ;;
    esac
}

is_desktop_path() {
    case "$1" in
        # Backend CI regenerates this file from the schema and replaces any hand edit. New endpoints in it stay unused until a desktop call site uses them, and call sites stay gated.
        products/desktop/packages/api-client/src/generated.ts) return 1 ;;
        products/desktop/*) return 0 ;;
        # The desktop app bundles these packages, and the agent npm release publishes them.
        packages/agent/packages/*) return 0 ;;
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
touched_rust=false
files=$(fetch_api --paginate "repos/$REPOSITORY/pulls/$PR_NUMBER/files" | jq -r '.[].filename') || exit 1
while IFS= read -r path; do
    [ -n "$path" ] || continue
    if is_desktop_path "$path"; then touched_desktop=true; fi
    if is_rust_path "$path"; then touched_rust=true; fi
done <<<"$files"

if [ "$touched_desktop" = false ]; then
    echo "No products/desktop changes; nothing to check."
    exit 0
fi

# Labels come from the API, not the event payload, so a rerun of this job sees
# a label change; desktop-backend-coupling-rerun.yml triggers that rerun.
pr_json=$(fetch_api "repos/$REPOSITORY/pulls/$PR_NUMBER") || exit 1
if jq -e '[.labels[]?.name] | index("desktop-skip-backend-check") != null' <<<"$pr_json" >/dev/null; then
    echo "::notice::PR #$PR_NUMBER carries desktop-skip-backend-check; skipping the coupling check."
    exit 0
fi

if [ "$touched_rust" = true ]; then
    echo "::error::This PR contains both desktop and Rust service changes. These must be separated into different PRs."
    echo ""
    echo "Why? Desktop and agent releases auto-update users. Each release waits until"
    echo "prod-us and prod-eu run a Django build that contains its commit, so Django"
    echo "changes can share a PR with desktop code. Rust services deploy separately, and"
    echo "the releases do not wait for them yet. If desktop code depends on a Rust change"
    echo "in the same PR, a release can ship a client that calls endpoints that are not"
    echo "deployed yet."
    echo ""
    echo "Solution: split into two PRs:"
    echo "  1. First PR: Rust changes only (merge and wait for the deploy)."
    echo "  2. Second PR: desktop changes (merge once the backend is live)."
    echo ""
    echo "If the two halves are independent (safe to ship in either order), apply the"
    echo "'desktop-skip-backend-check' label. The check reruns automatically."
    exit 1
fi

echo "No desktop/backend coupling detected."
