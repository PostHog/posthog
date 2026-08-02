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
UPDATE_FEED_URL="${UPDATE_FEED_URL:-https://desktop-releases.posthog.com/stable/latest.yml}"

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

# A GitHub API failure must fail the gate, not read as an empty result: a
# missed Requires-Backend declaration would ship a release its author said
# must wait.
fetch_api() {
    if ! gh api "$1"; then
        echo "::error::GitHub API request failed for $1; cannot verify backend dependencies" >&2
        return 1
    fi
}

# The range must start at the last version users can actually receive, not the
# last tag minted: releases are cumulative snapshots, and a predecessor release
# that failed, timed out or was dropped from the concurrency queue leaves its
# tag behind without publishing. Anchoring at a tag would silently drop that
# predecessor's backend requirements from the next release. The update feed's
# published version is the source of truth; when it cannot be resolved the
# fallback is the FULL desktop history, never a tag: over-inclusion is safe
# (already-deployed requirements pass the ancestry check instantly), a tag
# anchor is not.
published_anchor() {
    local version tag
    version=$(curl -fsSL --max-time 10 "$UPDATE_FEED_URL" 2>/dev/null | sed -n 's/^version:[[:space:]]*//p' | sed -n '1p') || true
    if [ -z "$version" ]; then
        echo "::warning::Could not read the update feed ($UPDATE_FEED_URL); walking the full desktop history instead" >&2
        return
    fi
    tag="desktop-v$version"
    if git rev-parse -q --verify "refs/tags/$tag^{commit}" >/dev/null; then
        echo "$tag"
    else
        echo "::warning::Update feed version $version has no $tag tag in this repo; walking the full desktop history instead" >&2
    fi
}

# Only commits touching products/desktop can couple or declare a dependency,
# so the walk is path-limited. The full-history walk (first release, feed
# unresolvable) has no range start, which also keeps the very first desktop
# commit inside the range, where an exclusive start..end would drop it.
range_commits() {
    if [ -n "${RANGE_START_SHA:-}" ]; then
        git rev-list --no-merges --reverse "$RANGE_START_SHA..$CURRENT_SHA" -- products/desktop
        return
    fi
    local anchor
    anchor=$(published_anchor)
    if [ -n "$anchor" ]; then
        echo "Release range: $anchor..$CURRENT_SHA (anchored at the published feed version)" >&2
        git rev-list --no-merges --reverse "$anchor..$CURRENT_SHA" -- products/desktop
    else
        echo "Walking the full desktop history up to $CURRENT_SHA" >&2
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

    pulls_json=$(fetch_api "repos/$REPOSITORY/commits/$sha/pulls") || exit 1
    pr_number=$(jq -r '.[0].number // empty' <<<"$pulls_json")
    pr_body=""
    skip_gate=false
    if [ -n "$pr_number" ]; then
        pr_json=$(fetch_api "repos/$REPOSITORY/pulls/$pr_number") || exit 1
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

    # PR bodies stay editable after merge, by external contributors too, so a
    # Requires-Backend declaration is trusted input only when the author has
    # write-side association. Anyone else's declarations are ignored loudly
    # rather than allowed to block (or having ever gated) a release.
    if [ -n "$pr_body" ] && grep -qiE '^requires-backend:' <<<"$pr_body"; then
        author_assoc=$(jq -r '.author_association // ""' <<<"$pr_json")
        case "$author_assoc" in
            OWNER | MEMBER | COLLABORATOR) ;;
            *)
                echo "::warning::PR #${pr_number:-unknown} declares Requires-Backend but its author association '$author_assoc' is not trusted; ignoring the declaration"
                pr_body=""
                ;;
        esac
    fi

    while IFS= read -r line; do
        ref=$(printf '%s' "$line" | cut -d: -f2- | tr -d ' #')
        [ -n "$ref" ] || continue
        # PR numbers cap at 9 digits so an unlucky all-numeric commit SHA
        # still routes to the commit branch below.
        if [[ "$ref" =~ ^[0-9]{1,9}$ ]]; then
            dep_json=$(fetch_api "repos/$REPOSITORY/pulls/$ref") || exit 1
            # merged must be checked explicitly: open PRs carry an ephemeral
            # test-merge merge_commit_sha, so non-emptiness proves nothing. A
            # declared dependency that is not merged must block, not ship.
            resolved=$(jq -r 'select(.merged == true) | .merge_commit_sha // empty' <<<"$dep_json")
            if [ -z "$resolved" ]; then
                echo "::error::PR #${pr_number:-unknown} declares Requires-Backend: #$ref but that PR is not merged; refusing to release ahead of it"
                exit 1
            fi
        else
            if ! git rev-parse -q --verify "$ref^{commit}" >/dev/null; then
                # A typo'd SHA would otherwise block every release until a
                # human intervenes, with only a generic deploy timeout as the
                # symptom. Fail fast and name the bad reference instead.
                echo "::error::PR #${pr_number:-unknown} declares Requires-Backend: $ref but no such commit exists in this repo"
                exit 1
            fi
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
