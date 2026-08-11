#!/usr/bin/env bash
set -euo pipefail

checker="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/check-pr-backend-coupling.sh"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# gh stub: prints the fixture registered for the requested path, fails on a
# .fail marker and 404s on anything unregistered. jq stays real.
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
    local number="$1" labels="$2"
    shift 2
    jq -n --argjson labels "$labels" '{labels: $labels}' \
        >"$fixtures/repos_PostHog_posthog_pulls_${number}.json"
    printf '%s\n' "$@" | jq -R '{filename: .}' | jq -s . \
        >"$fixtures/repos_PostHog_posthog_pulls_${number}_files.json"
}

run_checker() {
    PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" \
        REPOSITORY="PostHog/posthog" PR_NUMBER="$1" "$checker"
}

assert_result() {
    local name="$1" pr="$2" expected_status="$3" needle="$4" output status
    set +e
    output=$(run_checker "$pr" 2>&1)
    status=$?
    set -e
    if [ "$status" -ne "$expected_status" ] || ! grep -Fq "$needle" <<<"$output"; then
        echo "FAIL: $name (exit $status, expected $expected_status)"
        awk '{print "  | " $0}' <<<"$output"
        exit 1
    fi
    echo "ok: $name"
}

register_pr 1 "[]" products/desktop/apps/foo.ts products/desktop/README.md
assert_result "desktop-only PR passes" 1 0 "No desktop/backend coupling detected."

register_pr 2 "[]" posthog/models.py ee/billing/models.py
assert_result "backend-only PR is out of scope" 2 0 "No products/desktop changes"

register_pr 3 "[]" products/desktop/apps/foo.ts posthog/models.py
assert_result "coupled PR fails with split guidance" 3 1 "must be separated into different PRs"

register_pr 4 '[{"name": "skip-desktop-backend-check"}]' products/desktop/apps/foo.ts posthog/models.py
assert_result "skip label suppresses the check" 4 0 "skipping the coupling check"

# `yes` marks paths that count as backend and must fail the PR.
pr=100
while IFS='|' read -r path gated; do
    pr=$((pr + 1))
    register_pr "$pr" "[]" products/desktop/apps/foo.ts "$path"
    if [ "$gated" = yes ]; then
        assert_result "classifier arm $path is backend" "$pr" 1 "must be separated into different PRs"
    else
        assert_result "classifier arm $path is not backend" "$pr" 0 "No desktop/backend coupling detected."
    fi
done <<'CASES'
posthog/api/insight.py|yes
posthog/README.md|no
rust/capture/src/main.rs|yes
rust/capture/README.md|no
ee/billing/models.py|yes
ee/frontend/exports.ts|no
common/hogql_parser/parser.cpp|yes
products/llm_analytics/backend/api.py|yes
frontend/src/products.json|yes
pyproject.toml|no
frontend/src/scenes/App.tsx|no
CASES

register_pr 5 "[]" products/desktop/apps/foo.ts
touch "$fixtures/repos_PostHog_posthog_pulls_5_files.fail"
assert_result "file listing API failure fails closed" 5 1 "GitHub API request failed"

register_pr 6 "[]" products/desktop/apps/foo.ts
touch "$fixtures/repos_PostHog_posthog_pulls_6.fail"
assert_result "label lookup API failure fails closed" 6 1 "GitHub API request failed"

echo "PR backend coupling check regression cases passed."
