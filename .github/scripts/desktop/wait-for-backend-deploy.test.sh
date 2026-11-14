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

trusted="deployment-status-posthog[bot]"

# Registers one page of deployments for an environment, newest created first.
# Each argument is "<id>:<sha>:<updated minute>:<statuses>[:<status creator>[:<deployment creator>]]",
# with statuses comma-separated, newest first. The stub serves the whole status
# history even for per_page=1, so the waiter must read only the first entry.
# The updated minute becomes updated_at, and both creators default to the trusted App.
register_page() {
    local fixtures="$1" environment="$2" page="$3" entry id sha minute states status_by deploy_by
    shift 3
    mkdir -p "$fixtures"
    for entry in "$@"; do
        IFS=: read -r id sha minute states status_by deploy_by <<<"$entry"
        jq -n --arg id "$id" --arg sha "$sha" --arg minute "$minute" --arg by "${deploy_by:-$trusted}" \
            '{id: ($id | tonumber), sha: $sha, updated_at: "2026-11-13T10:\($minute):00Z", creator: {login: $by}}'
        jq -n --arg states "$states" --arg by "${status_by:-$trusted}" '$states | split(",") | map({state: ., creator: {login: $by}})' \
            >"$fixtures/repos_PostHog_posthog_deployments_${id}_statuses_per_page_1.json"
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

register_page "$workdir/live" prod-us 1 "11:$c3:10:success"
register_page "$workdir/live" prod-eu 1 "21:$c4:10:success"
assert_result "both environments live on a descendant" "$workdir/live" 0 "Every environment runs"

# A rollback to a sha never deployed before gets a new record, and that record is live.
register_page "$workdir/rollback" prod-us 1 "12:$c3:10:success"
register_page "$workdir/rollback" prod-eu 1 "23:$c1:50:success" "22:$c4:40:inactive,success"
assert_result "a rollback to an older sha holds the release" "$workdir/rollback" 3 "prod-eu: live ${c1:0:12}, contains: no"

# A rollback to a sha deployed before posts success on that sha's older record.
register_page "$workdir/reused" prod-us 1 "32:$c4:50:inactive,success" "31:$c1:55:success,inactive,success"
register_page "$workdir/reused" prod-eu 1 "33:$c4:10:success"
assert_result "a rollback that reuses an older record holds the release" "$workdir/reused" 3 "prod-us: live ${c1:0:12}, contains: no"

# charts writes the inactive status best-effort, so two records can end on success.
# The one updated last is live.
register_page "$workdir/missed-inactive" prod-us 1 "35:$c4:50:success" "34:$c1:55:success"
register_page "$workdir/missed-inactive" prod-eu 1 "36:$c4:10:success"
assert_result "the most recently updated success is live" "$workdir/missed-inactive" 3 "prod-us: live ${c1:0:12}, contains: no"

register_page "$workdir/rolling" prod-us 1 "14:$c4:60:in_progress" "13:$c3:50:success,in_progress"
register_page "$workdir/rolling" prod-eu 1 "24:$c2:10:success"
assert_result "an in-progress deploy leaves the previous success live" "$workdir/rolling" 0 "prod-us: live ${c3:0:12}, contains: yes"

# A full first page of failed deploys pushes the live record to page 2.
failed=()
for id in $(seq 100 129); do
    failed+=("$id:$c4:40:failure")
done
register_page "$workdir/paged" prod-us 1 "${failed[@]}"
register_page "$workdir/paged" prod-us 2 "19:$c3:30:success"
register_page "$workdir/paged" prod-eu 1 "27:$c4:10:success"
assert_result "the live deployment on page 2 is found" "$workdir/paged" 0 "prod-us: live ${c3:0:12}, contains: yes"

# Any token with deployments: write can post a success, so only the charts App counts.
register_page "$workdir/forged" prod-us 1 \
    "43:$c4:61:success:someone-else" "41:$c4:60:success::someone-else" "42:$c1:50:success"
register_page "$workdir/forged" prod-eu 1 "44:$c4:10:success"
assert_result "a success from another creator does not count" "$workdir/forged" 3 "prod-us: live ${c1:0:12}, contains: no"

register_page "$workdir/api-failure" prod-us 1 "15:$c4:10:success"
touch "$workdir/api-failure/repos_PostHog_posthog_deployments_environment_prod-eu_task_deploy_per_page_30_page_1.fail"
assert_result "an API failure is not read as deployed" "$workdir/api-failure" 1 "prod-eu: GitHub API request failed"

echo "Backend deploy wait regression cases passed."
