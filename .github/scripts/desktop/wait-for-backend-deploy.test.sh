#!/usr/bin/env bash
set -euo pipefail

waiter="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/wait-for-backend-deploy.sh"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# gh stub: prints the fixture registered for the requested path, fails on a
# .fail marker and 404s on anything unregistered. jq stays real.
fake_bin="$workdir/bin"
mkdir -p "$fake_bin"
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

# A real linear history, so the ancestry check runs against real git.
repo="$workdir/repo"
git init --quiet "$repo"
for n in 1 2 3 4; do
    git -C "$repo" -c user.name=test -c user.email=test@example.com -c commit.gpgsign=false \
        commit --quiet --allow-empty -m "commit $n"
done
c1=$(git -C "$repo" rev-parse HEAD~3)
c2=$(git -C "$repo" rev-parse HEAD~2)
c3=$(git -C "$repo" rev-parse HEAD~1)
c4=$(git -C "$repo" rev-parse HEAD)

# Registers deployments for one environment, newest first. Each argument is
# "<id>:<sha>:<statuses>", with statuses comma-separated, newest first.
register_environment() {
    local fixtures="$1" environment="$2" entry id sha states
    shift 2
    mkdir -p "$fixtures"
    for entry in "$@"; do
        IFS=: read -r id sha states <<<"$entry"
        jq -n --arg id "$id" --arg sha "$sha" '{id: ($id | tonumber), sha: $sha}'
        jq -n --arg states "$states" '$states | split(",") | map({state: .})' \
            >"$fixtures/repos_PostHog_posthog_deployments_${id}_statuses_per_page_100.json"
    done | jq -s . >"$fixtures/repos_PostHog_posthog_deployments_environment_${environment}_task_deploy_per_page_30.json"
}

assert_result() {
    local name="$1" fixtures="$2" expected_status="$3" needle="$4" output status
    set +e
    output=$(cd "$repo" && PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" \
        REPOSITORY="PostHog/posthog" COMMIT_SHA="$c2" \
        TIMEOUT_SECONDS=1 INTERVAL_SECONDS=1 "$waiter" 2>&1)
    status=$?
    set -e
    if [ "$status" -ne "$expected_status" ] || ! grep -Fq "$needle" <<<"$output"; then
        echo "FAIL: $name (exit $status, expected $expected_status)"
        awk '{print "  | " $0}' <<<"$output"
        exit 1
    fi
    echo "ok: $name"
}

register_environment "$workdir/live" prod-us "11:$c3:success"
register_environment "$workdir/live" prod-eu "21:$c4:success"
assert_result "both environments live on a descendant" "$workdir/live" 0 "Every environment runs"

# A rollback deploys an older sha and gets its own success, so it is live again.
register_environment "$workdir/rollback" prod-us "12:$c3:success"
register_environment "$workdir/rollback" prod-eu "23:$c1:success" "22:$c4:inactive,success"
assert_result "a rollback to an older sha holds the release" "$workdir/rollback" 3 "prod-eu: live ${c1:0:12}, contains: no"

register_environment "$workdir/rolling" prod-us "14:$c4:in_progress" "13:$c3:success,in_progress"
register_environment "$workdir/rolling" prod-eu "24:$c2:success"
assert_result "an in-progress deploy leaves the previous success live" "$workdir/rolling" 0 "prod-us: live ${c3:0:12}, contains: yes"

# A deploy of another task in the same environment marks the live Django
# deployment inactive, and it stays live.
register_environment "$workdir/other-task" prod-us "16:$c3:inactive,success,in_progress"
register_environment "$workdir/other-task" prod-eu "26:$c4:success"
assert_result "another task's deploy does not hide the live build" "$workdir/other-task" 0 "prod-us: live ${c3:0:12}, contains: yes"

register_environment "$workdir/api-failure" prod-us "15:$c4:success"
touch "$workdir/api-failure/repos_PostHog_posthog_deployments_environment_prod-eu_task_deploy_per_page_30.fail"
assert_result "an API failure is not read as deployed" "$workdir/api-failure" 1 "prod-eu: GitHub API request failed"

echo "Backend deploy wait regression cases passed."
