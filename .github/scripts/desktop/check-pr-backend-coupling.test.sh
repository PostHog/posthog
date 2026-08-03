#!/usr/bin/env bash
set -euo pipefail

checker="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check-pr-backend-coupling.sh"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# gh stub: `gh api [flags] <path>` prints the fixture registered for that
# path, fails when a .fail marker exists and 404s on anything unregistered,
# matching the script's fail-closed contract. jq stays real.
fake_bin="$workdir/bin"
fixtures="$workdir/fixtures"
mkdir -p "$fake_bin" "$fixtures"
cat >"$fake_bin/gh" <<'EOF'
#!/usr/bin/env bash
path=""
for arg in "$@"; do
    case "$arg" in
        api | --*) ;;
        *)
            path="$arg"
            break
            ;;
    esac
done
slug=$(printf '%s' "${path:?}" | tr '/?&=' '____')
if [ -f "$GH_FIXTURE_DIR/$slug.fail" ]; then
    echo "stubbed API failure for $path" >&2
    exit 1
elif [ -f "$GH_FIXTURE_DIR/$slug.json" ]; then
    cat "$GH_FIXTURE_DIR/$slug.json"
else
    echo "stubbed 404 for $path" >&2
    exit 1
fi
EOF
chmod +x "$fake_bin/gh"

register_pr() {
    local number="$1" body="$2" labels="$3" assoc="$4"
    shift 4
    jq -n --arg body "$body" --argjson labels "$labels" --arg assoc "$assoc" \
        '{body: $body, labels: $labels, author_association: $assoc}' \
        >"$fixtures/repos_PostHog_posthog_pulls_${number}.json"
    printf '%s\n' "$@" | jq -R '{filename: .}' | jq -s . \
        >"$fixtures/repos_PostHog_posthog_pulls_${number}_files.json"
}

run_checker() {
    PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" \
        REPOSITORY="PostHog/posthog" PR_NUMBER="$1" "$checker"
}

assert_passes() {
    local name="$1" pr="$2" needle="$3" output status
    set +e
    output=$(run_checker "$pr" 2>&1)
    status=$?
    set -e
    if [ "$status" -ne 0 ] || ! grep -Fq "$needle" <<<"$output"; then
        echo "FAIL: $name (exit $status)"
        awk '{print "  | " $0}' <<<"$output"
        exit 1
    fi
    echo "ok: $name"
}

assert_fails() {
    local name="$1" pr="$2" needle="$3" output status
    set +e
    output=$(run_checker "$pr" 2>&1)
    status=$?
    set -e
    if [ "$status" -eq 0 ] || ! grep -Fq "$needle" <<<"$output"; then
        echo "FAIL: $name (exit $status)"
        awk '{print "  | " $0}' <<<"$output"
        exit 1
    fi
    echo "ok: $name"
}

register_pr 1 "" "[]" MEMBER products/desktop/apps/foo.ts products/desktop/README.md
assert_passes "desktop-only PR passes" 1 "No backend coupling detected."

register_pr 2 "" "[]" MEMBER posthog/models.py ee/billing/models.py
assert_passes "backend-only PR is out of scope" 2 "No products/desktop changes"

register_pr 3 "" "[]" MEMBER products/desktop/apps/foo.ts posthog/models.py
assert_fails "coupled PR fails with split guidance" 3 "changes both products/desktop and backend"

register_pr 4 "" '[{"name": "desktop-skip-backend-gate"}]' MEMBER products/desktop/apps/foo.ts posthog/models.py
assert_passes "skip label suppresses the check" 4 "skipping the coupling check"

register_pr 5 "" "[]" MEMBER products/desktop/apps/foo.ts posthog/README.md ee/frontend/exports.ts pyproject.toml
assert_passes "docs and tooling paths never count as backend" 5 "No backend coupling detected."

echo '{"merged": true, "merge_commit_sha": "1234123412341234123412341234123412341234"}' \
    >"$fixtures/repos_PostHog_posthog_pulls_77.json"
register_pr 6 $'Adds a thing.\r\n\r\nRequires-Backend: #77' "[]" MEMBER products/desktop/apps/foo.ts
assert_passes "merged Requires-Backend PR passes" 6 "Requires-Backend: #77 is merged."

# Open PRs still carry an ephemeral test-merge merge_commit_sha; only
# merged: true may satisfy the dependency.
echo '{"merged": false, "merge_commit_sha": "cafecafecafecafecafecafecafecafecafecafe"}' \
    >"$fixtures/repos_PostHog_posthog_pulls_99.json"
register_pr 7 "Requires-Backend: 99" "[]" MEMBER products/desktop/apps/foo.ts
assert_fails "unmerged Requires-Backend PR fails" 7 "Requires-Backend: #99 is not merged."

register_pr 8 "Requires-Backend: #4242" "[]" MEMBER products/desktop/apps/foo.ts
assert_fails "nonexistent Requires-Backend PR fails" 8 "could not be fetched"

good_sha="1111111111111111111111111111111111111111"
echo '{}' >"$fixtures/repos_PostHog_posthog_commits_${good_sha}.json"
register_pr 9 "Requires-Backend: $good_sha" "[]" MEMBER products/desktop/apps/foo.ts
assert_passes "existing Requires-Backend sha passes" 9 "resolves to a commit"

register_pr 10 "Requires-Backend: 000000000000000000000000000000000000dead" "[]" MEMBER products/desktop/apps/foo.ts
assert_fails "unknown Requires-Backend sha fails" 10 "does not resolve to a commit"

register_pr 11 "Requires-Backend: #98" "[]" CONTRIBUTOR products/desktop/apps/foo.ts
assert_passes "untrusted author declarations warn instead of enforcing a no-op" 11 "ignored by the release gate"

register_pr 12 "" "[]" MEMBER products/desktop/apps/foo.ts
touch "$fixtures/repos_PostHog_posthog_pulls_12_files.fail"
assert_fails "file listing API failure fails closed" 12 "GitHub API request failed"

echo "PR backend coupling check regression cases passed."
