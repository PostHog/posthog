#!/usr/bin/env bash
# Sourced by check-pr-backend-coupling.sh (PR-time separation check in
# desktop-ci.yml) and detect-backend-coupling.sh (release-time gate in
# desktop-release.yml) so both layers classify paths and parse declarations
# identically: a PR the review-time check waves through must never surprise
# the release gate, and vice versa.

# Deploy-relevant subset of ci-backend.yml's `backend` filter: only paths that
# ship in the deployed image. Its tooling/test entries (pyproject.toml, uv.lock,
# conftest.py, docker-compose*, ...) are deliberately excluded so they cannot
# hold a release hostage.
is_backend_path() {
    case "$1" in
        *.md | *.mdx) return 1 ;;
        products/desktop/*) return 1 ;;
        posthog/*) return 0 ;;
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

# Reads a PR body on stdin and emits each Requires-Backend ref (sha or PR
# number, "#" and spaces stripped) on its own line.
requires_backend_refs() {
    grep -iE '^requires-backend:' | cut -d: -f2- | tr -d ' #' | awk 'NF'
}

# PR numbers cap at 9 digits so an unlucky all-numeric commit SHA still routes
# to the commit branch.
is_pr_number_ref() {
    [[ "$1" =~ ^[0-9]{1,9}$ ]]
}
