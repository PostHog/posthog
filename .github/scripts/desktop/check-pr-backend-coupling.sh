#!/usr/bin/env bash
# PR-time half of the desktop backend-deploy gate: fails any PR that changes
# both products/desktop/** and backend code that ships in the Django image, so
# coupled work gets split into sequenced PRs at review time instead of
# surfacing later as a stalled release. Also validates Requires-Backend
# declarations early: the declared backend PR must be merged before the
# desktop PR may land, because the release-time gate hard-fails on unmerged
# dependencies. The release-time gate (detect-backend-coupling.sh) still waits
# for the actual deploy, since merge order cannot guarantee deploy order.
set -euo pipefail

REPOSITORY="${REPOSITORY:?}"
PR_NUMBER="${PR_NUMBER:?}"

# shellcheck source=.github/scripts/desktop/backend-coupling-paths.sh
source "$(dirname "${BASH_SOURCE[0]}")/backend-coupling-paths.sh"

# An API failure must fail the check, not read as an empty result: a missed
# coupling or declaration here would resurface as a release stalled in
# desktop-release.yml, far from the PR that caused it.
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

pr_json=$(fetch_api "repos/$REPOSITORY/pulls/$PR_NUMBER") || exit 1

# Labels are read from the API, not the workflow event payload, so applying
# the skip label and re-running this check is enough; label changes do not
# retrigger pull_request runs.
if jq -e '[.labels[]?.name] | index("desktop-skip-backend-gate") != null' <<<"$pr_json" >/dev/null; then
    echo "::notice::PR #$PR_NUMBER carries desktop-skip-backend-gate; skipping the coupling check."
    exit 0
fi

if [ "$touched_backend" = true ]; then
    echo "::error::This PR changes both products/desktop and backend code that ships in the Django image."
    echo ""
    echo "Desktop releases auto-update users, so the release gate holds the update feed until the"
    echo "backend half of a coupled change is deployed. Merging both halves together means every"
    echo "desktop release containing this commit can stall waiting on a backend deploy."
    echo ""
    echo "Split the work into two PRs, merged in order:"
    echo "  1. Backend changes first."
    echo "  2. Desktop changes second, with a 'Requires-Backend: <PR number or sha>' line in the"
    echo "     PR body so the release gate waits for that deploy."
    echo ""
    echo "If the two halves are independent (safe to release in either order), apply the"
    echo "'desktop-skip-backend-gate' label and re-run this check."
    exit 1
fi

pr_body=$(jq -r '.body // ""' <<<"$pr_json" | tr -d '\r')
if ! grep -qiE '^requires-backend:' <<<"$pr_body"; then
    echo "No backend coupling detected."
    exit 0
fi

# The release gate only trusts declarations from write-side authors (PR bodies
# stay editable after merge), so validating anyone else's would enforce a
# no-op. Warn instead of failing: the declaration will be ignored at release
# time unless a maintainer adopts it.
author_assoc=$(jq -r '.author_association // ""' <<<"$pr_json")
case "$author_assoc" in
    OWNER | MEMBER | COLLABORATOR) ;;
    *)
        echo "::warning::Requires-Backend declarations from author association '$author_assoc' are ignored by the release gate; a maintainer must re-declare them if the dependency is real."
        exit 0
        ;;
esac

while IFS= read -r ref; do
    if is_pr_number_ref "$ref"; then
        if ! dep_json=$(gh api "repos/$REPOSITORY/pulls/$ref"); then
            echo "::error::Requires-Backend: #$ref could not be fetched (nonexistent PR or API failure); refusing to pass without verifying it."
            exit 1
        fi
        if ! jq -e '.merged == true' <<<"$dep_json" >/dev/null; then
            echo "::error::Requires-Backend: #$ref is not merged. Merge the backend PR first, then re-run this check; the release gate refuses to release ahead of an unmerged dependency."
            exit 1
        fi
        echo "Requires-Backend: #$ref is merged."
    else
        if ! gh api "repos/$REPOSITORY/commits/$ref" >/dev/null; then
            echo "::error::Requires-Backend: $ref does not resolve to a commit in $REPOSITORY (or the lookup failed). A bad reference here would block every desktop release until fixed."
            exit 1
        fi
        echo "Requires-Backend: $ref resolves to a commit."
    fi
done < <(requires_backend_refs <<<"$pr_body")

echo "All Requires-Backend declarations check out."
