#!/usr/bin/env bash
set -euo pipefail

detector="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/detect-backend-coupling.sh"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# gh stub: `gh api <path>` prints the fixture registered for that path,
# else an empty list/object. jq stays real.
fake_bin="$workdir/bin"
fixtures="$workdir/fixtures"
mkdir -p "$fake_bin" "$fixtures"
cat >"$fake_bin/gh" <<'EOF'
#!/usr/bin/env bash
slug=$(printf '%s' "${2:?}" | tr '/?&=' '____')
if [ -f "$GH_FIXTURE_DIR/$slug.json" ]; then
    cat "$GH_FIXTURE_DIR/$slug.json"
elif [[ "${2}" == */pulls ]]; then
    echo '[]'
else
    echo '{}'
fi
EOF
chmod +x "$fake_bin/gh"

repo="$workdir/repo"
mkdir -p "$repo"
git -C "$repo" -c init.defaultBranch=main init -q
git -C "$repo" config user.email test@example.com
git -C "$repo" config user.name test

commit() {
    local message="$1"
    shift
    for path in "$@"; do
        mkdir -p "$repo/$(dirname "$path")"
        echo "$message" >"$repo/$path"
        git -C "$repo" add "$path"
    done
    git -C "$repo" commit -qm "$message"
    git -C "$repo" rev-parse HEAD
}

register_pr() {
    local sha="$1" number="$2" body="$3" labels="$4"
    echo "[{\"number\": $number}]" >"$fixtures/repos_PostHog_posthog_commits_${sha}_pulls.json"
    jq -n --arg body "$body" --argjson labels "$labels" '{body: $body, labels: $labels}' \
        >"$fixtures/repos_PostHog_posthog_pulls_${number}.json"
}

run_detector() {
    (cd "$repo" && PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" REPOSITORY="PostHog/posthog" \
        CURRENT_TAG="${CURRENT_TAG:-}" CURRENT_SHA="$(git -C "$repo" rev-parse HEAD)" "$detector")
}

assert_required() {
    local name="$1" expected="$2" output actual
    output=$(run_detector)
    actual=$(sed -n 's/^required_shas=//p' <<<"$output")
    if [ "$actual" != "$expected" ]; then
        echo "FAIL: $name"
        echo "  expected required_shas: '$expected'"
        echo "  actual required_shas:   '$actual'"
        awk '{print "  | " $0}' <<<"$output"
        exit 1
    fi
    echo "ok: $name"
}

commit "base" README.md >/dev/null
git -C "$repo" tag desktop-v0.1.0
export CURRENT_TAG=""

commit "desktop only" products/desktop/apps/foo.ts >/dev/null
assert_required "desktop-only commit does not gate" ""

coupled=$(commit "desktop plus backend" products/desktop/apps/bar.ts posthog/models.py)
assert_required "coupled commit gates on its own sha" "$coupled"

commit "backend only" posthog/api.py >/dev/null
assert_required "backend-only commit does not gate" "$coupled"

commit "docs both sides" products/desktop/README2.md posthog/README.md >/dev/null
assert_required "markdown never counts as backend" "$coupled"

commit "tooling change" products/desktop/apps/baz.ts pyproject.toml conftest.py >/dev/null
assert_required "tooling paths never count as backend" "$coupled"

trailer_sha=$(commit "desktop with trailer" products/desktop/apps/qux.ts)
backend_dep="aaaabbbbccccddddeeeeffff0000111122223333"
merged_dep="1234123412341234123412341234123412341234"
register_pr "$trailer_sha" 42 $'Adds a thing.\r\n\r\nRequires-Backend: '"$backend_dep"$'\r\nRequires-Backend: #77\r\nRequires-Backend: 99' "[]"
echo "{\"merge_commit_sha\": \"$merged_dep\"}" >"$fixtures/repos_PostHog_posthog_pulls_77.json"
echo '{}' >"$fixtures/repos_PostHog_posthog_pulls_99.json"
assert_required "trailers resolve shas and merged PRs, skip unmerged" "$coupled $backend_dep $merged_dep"

skipped=$(commit "coupled but skipped" products/desktop/apps/skip.ts posthog/skip.py)
register_pr "$skipped" 43 "" '[{"name": "desktop-skip-backend-gate"}]'
assert_required "skip label suppresses the gate" "$coupled $backend_dep $merged_dep"

git -C "$repo" tag desktop-v0.2.0
export CURRENT_TAG="desktop-v0.2.0"
assert_required "range excludes commits at or before the previous tag" "$coupled $backend_dep $merged_dep"

pretag=$(git -C "$repo" rev-parse HEAD)
posttag=$(commit "coupled after tag" products/desktop/apps/late.ts posthog/late.py)
export CURRENT_TAG=""
output=$(cd "$repo" && PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" REPOSITORY="PostHog/posthog" \
    RANGE_START_SHA="$pretag" CURRENT_SHA="$posttag" "$detector")
actual=$(sed -n 's/^required_shas=//p' <<<"$output")
if [ "$actual" != "$posttag" ]; then
    echo "FAIL: explicit range override walks only start..end"
    echo "  expected '$posttag', got '$actual'"
    exit 1
fi
echo "ok: explicit range override walks only start..end"

first_repo="$workdir/first-release"
mkdir -p "$first_repo"
git -C "$first_repo" -c init.defaultBranch=main init -q
git -C "$first_repo" config user.email test@example.com
git -C "$first_repo" config user.name test
mkdir -p "$first_repo/products/desktop" "$first_repo/posthog"
echo x >"$first_repo/products/desktop/app.ts"
echo x >"$first_repo/posthog/models.py"
git -C "$first_repo" add . && git -C "$first_repo" commit -qm "initial import"
root_sha=$(git -C "$first_repo" rev-parse HEAD)
output=$(cd "$first_repo" && PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" REPOSITORY="PostHog/posthog" \
    CURRENT_SHA="$root_sha" "$detector")
actual=$(sed -n 's/^required_shas=//p' <<<"$output")
if [ "$actual" != "$root_sha" ]; then
    echo "FAIL: first release includes the root desktop commit"
    echo "  expected '$root_sha', got '$actual'"
    exit 1
fi
echo "ok: first release includes the root desktop commit"

echo "Backend coupling detector regression cases passed."
