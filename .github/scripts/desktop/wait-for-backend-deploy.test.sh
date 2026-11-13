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

# A linear master: c1 is the oldest commit and c4 the newest. The waiter asks
# whether a deployment contains c2.
c1=1111111111111111111111111111111111111111
c2=2222222222222222222222222222222222222222
c3=3333333333333333333333333333333333333333
c4=4444444444444444444444444444444444444444
compares="$workdir/compares"
mkdir -p "$compares"
register_compare() {
    jq -n --arg status "$2" '{status: $status}' \
        >"$compares/repos_PostHog_posthog_compare_$c2...$1.json"
}
register_compare "$c1" behind
register_compare "$c2" identical
register_compare "$c3" ahead
register_compare "$c4" ahead
register_compare master ahead

# Registers one page of deployments for an environment, newest first. Each
# argument is "<id>:<sha>:<statuses>", with statuses comma-separated, newest first.
register_page() {
    local fixtures="$1" environment="$2" page="$3" entry id sha states
    shift 3
    mkdir -p "$fixtures"
    for entry in "$@"; do
        IFS=: read -r id sha states <<<"$entry"
        jq -n --arg id "$id" --arg sha "$sha" '{id: ($id | tonumber), sha: $sha}'
        jq -n --arg states "$states" '$states | split(",") | map({state: .})' \
            >"$fixtures/repos_PostHog_posthog_deployments_${id}_statuses_per_page_100.json"
    done | jq -s . >"$fixtures/repos_PostHog_posthog_deployments_environment_${environment}_task_deploy_per_page_30_page_${page}.json"
}

assert_result() {
    local name="$1" fixtures="$2" expected_status="$3" needle="$4" output status
    cp "$compares"/* "$fixtures"/
    set +e
    output=$(PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" \
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

register_page "$workdir/live" prod-us 1 "11:$c3:success"
register_page "$workdir/live" prod-eu 1 "21:$c4:success"
assert_result "both environments live on a descendant" "$workdir/live" 0 "Every environment runs"

# A rollback deploys an older sha and gets its own success, so it is live again.
register_page "$workdir/rollback" prod-us 1 "12:$c3:success"
register_page "$workdir/rollback" prod-eu 1 "23:$c1:success" "22:$c4:inactive,success"
assert_result "a rollback to an older sha holds the release" "$workdir/rollback" 3 "prod-eu: live ${c1:0:12}, contains: no"

register_page "$workdir/rolling" prod-us 1 "14:$c4:in_progress" "13:$c3:success,in_progress"
register_page "$workdir/rolling" prod-eu 1 "24:$c2:success"
assert_result "an in-progress deploy leaves the previous success live" "$workdir/rolling" 0 "prod-us: live ${c3:0:12}, contains: yes"

# A deploy of another task in the same environment marks the live Django
# deployment inactive, and it stays live.
register_page "$workdir/other-task" prod-us 1 "16:$c3:inactive,success,in_progress"
register_page "$workdir/other-task" prod-eu 1 "26:$c4:success"
assert_result "another task's deploy does not hide the live build" "$workdir/other-task" 0 "prod-us: live ${c3:0:12}, contains: yes"

# A run of failed deploys can push the live one past the first page.
register_page "$workdir/paged" prod-us 1 "18:$c4:failure" "17:$c4:error,in_progress"
register_page "$workdir/paged" prod-us 2 "19:$c3:inactive,success"
register_page "$workdir/paged" prod-eu 1 "27:$c4:success"
assert_result "the live deployment on a later page is found" "$workdir/paged" 0 "prod-us: live ${c3:0:12}, contains: yes"

register_page "$workdir/api-failure" prod-us 1 "15:$c4:success"
mkdir -p "$workdir/api-failure"
touch "$workdir/api-failure/repos_PostHog_posthog_deployments_environment_prod-eu_task_deploy_per_page_30_page_1.fail"
assert_result "an API failure is not read as deployed" "$workdir/api-failure" 1 "prod-eu: GitHub API request failed"

echo "Backend deploy wait regression cases passed."
