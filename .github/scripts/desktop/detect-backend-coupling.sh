#!/usr/bin/env bash
# Finds commits in a desktop release range whose backend half must be deployed
# before the release may reach the update feed. A commit is coupled when it
# touches both products/desktop/** and deploy-relevant backend paths; a desktop
# PR can also declare a dependency on a separately merged backend PR with a
# "Requires-Backend: <sha|PR number>" line in its body. The body is the only
# place such a declaration can live: squash merges in this repo keep the PR
# title only. A desktop-skip-backend-gate label on the PR suppresses both
# signals. Known gap: rust services are not gated (prod-us/prod-eu deployments
# track the Django image).
set -euo pipefail

REPOSITORY="${REPOSITORY:?}"
GITHUB_OUTPUT="${GITHUB_OUTPUT:-/dev/stdout}"
CURRENT_SHA="${CURRENT_SHA:-$(git rev-parse "${CURRENT_TAG:?}")}"

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
        *) return 1 ;;
    esac
}

is_desktop_path() {
    case "$1" in
        products/desktop/*) return 0 ;;
        *) return 1 ;;
    esac
}

# Only commits touching products/desktop can couple or declare a dependency,
# so the walk is path-limited. The first release has no previous desktop-v*
# tag; walking the full (path-limited) history keeps the very first desktop
# commit inside the range, which an exclusive start..end would drop.
range_commits() {
    if [ -n "${RANGE_START_SHA:-}" ]; then
        git rev-list --no-merges --reverse "$RANGE_START_SHA..$CURRENT_SHA" -- products/desktop
        return
    fi
    local prev_tag
    prev_tag=$(git tag --list 'desktop-v*' --sort=-v:refname | grep -vFx -- "${CURRENT_TAG:-}" | sed -n '1p') || true
    if [ -n "$prev_tag" ]; then
        echo "Release range: $prev_tag..$CURRENT_SHA" >&2
        git rev-list --no-merges --reverse "$prev_tag..$CURRENT_SHA" -- products/desktop
    else
        echo "No previous desktop-v* tag (first release); walking full desktop history" >&2
        git rev-list --no-merges --reverse "$CURRENT_SHA" -- products/desktop
    fi
}

REQUIRED=()

while IFS= read -r sha; do
    touched_desktop=false
    touched_backend=false
    while IFS= read -r path; do
        if is_desktop_path "$path"; then touched_desktop=true; fi
        if is_backend_path "$path"; then touched_backend=true; fi
    done < <(git diff-tree --root --no-commit-id --name-only -r "$sha")

    [ "$touched_desktop" = true ] || continue

    pr_number=$(gh api "repos/$REPOSITORY/commits/$sha/pulls" 2>/dev/null | jq -r '.[0].number // empty' || true)
    pr_body=""
    skip_gate=false
    if [ -n "$pr_number" ]; then
        pr_json=$(gh api "repos/$REPOSITORY/pulls/$pr_number" 2>/dev/null || echo '{}')
        pr_body=$(jq -r '.body // ""' <<<"$pr_json" | tr -d '\r')
        if jq -e '[.labels[]?.name] | index("desktop-skip-backend-gate") != null' <<<"$pr_json" >/dev/null; then
            skip_gate=true
            echo "PR #$pr_number carries desktop-skip-backend-gate; not gating on $sha"
        fi
    fi
    [ "$skip_gate" = false ] || continue

    if [ "$touched_backend" = true ]; then
        echo "Coupled commit $sha (PR #${pr_number:-unknown}) touches products/desktop and backend paths"
        REQUIRED+=("$sha")
    fi

    while IFS= read -r line; do
        ref=$(printf '%s' "$line" | cut -d: -f2- | tr -d ' #')
        [ -n "$ref" ] || continue
        if [[ "$ref" =~ ^[0-9]+$ ]]; then
            resolved=$(gh api "repos/$REPOSITORY/pulls/$ref" 2>/dev/null | jq -r '.merge_commit_sha // empty' || true)
            if [ -z "$resolved" ]; then
                echo "::warning::PR #${pr_number:-unknown} declares Requires-Backend: #$ref but that PR has no merge commit; ignoring"
                continue
            fi
        else
            resolved="$ref"
        fi
        echo "PR #${pr_number:-unknown} requires backend $resolved (Requires-Backend: $ref)"
        REQUIRED+=("$resolved")
    done < <(grep -iE '^requires-backend:' <<<"$pr_body" || true)
done < <(range_commits)

UNIQUE=$(printf '%s\n' ${REQUIRED[@]+"${REQUIRED[@]}"} | awk 'NF && !seen[$0]++' | paste -sd' ' -)
if [ -n "$UNIQUE" ]; then
    echo "Backend deploy required before this release goes live: $UNIQUE"
else
    echo "No backend-coupled changes in this release range; nothing to wait for."
fi
echo "required_shas=$UNIQUE" >>"$GITHUB_OUTPUT"
