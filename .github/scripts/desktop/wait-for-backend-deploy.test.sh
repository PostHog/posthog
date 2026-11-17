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
echo "$slug" >>"$GH_FIXTURE_DIR/calls"
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
# with statuses comma-separated, newest first. A status written "state@login" has
# its own creator. The updated minute becomes updated_at, and both creators
# default to the trusted App.
register_page() {
    local fixtures="$1" environment="$2" page="$3" entry id sha minute states status_by deploy_by
    shift 3
    mkdir -p "$fixtures"
    for entry in "$@"; do
        IFS=: read -r id sha minute states status_by deploy_by <<<"$entry"
        jq -n --arg id "$id" --arg sha "$sha" --arg minute "$minute" --arg by "${deploy_by:-$trusted}" \
            '{id: ($id | tonumber), sha: $sha, updated_at: "2026-11-13T10:\($minute):00Z", creator: {login: $by}}'
        jq -n --arg states "$states" --arg by "${status_by:-$trusted}" \
            '$states | split(",") | map(split("@") | {state: .[0], creator: {login: (.[1] // $by)}})' \
            >"$fixtures/repos_PostHog_posthog_deployments_${id}_statuses_per_page_100.json"
    done | jq -s . >"$fixtures/repos_PostHog_posthog_deployments_environment_${environment}_task_deploy_per_page_30_page_${page}.json"
}

assert_result() {
    local name="$1" fixtures="$2" expected_status="$3" needle="$4" output status
    cp "$compares"/* "$fixtures"/
    set +e
    output=$(PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" \
        REPOSITORY="PostHog/posthog" COMMIT_SHA="$c2" \
        TIMEOUT_SECONDS="${CASE_TIMEOUT_SECONDS:-1}" INTERVAL_SECONDS=1 "$waiter" 2>&1)
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

# The newest record was retired, so the older live record holds the release.
register_page "$workdir/retired" prod-us 1 "32:$c4:50:inactive,success" "31:$c1:55:success"
register_page "$workdir/retired" prod-eu 1 "33:$c4:10:success"
assert_result "a retired newest record leaves the older live one" "$workdir/retired" 3 "prod-us: live ${c1:0:12}, contains: no"

# charts writes the inactive status best-effort, so two records can end on success.
# Every deploy gets its own record, so the newest created one is live, whatever updated_at says.
register_page "$workdir/missed-inactive" prod-us 1 "35:$c4:50:success" "34:$c1:55:success"
register_page "$workdir/missed-inactive" prod-eu 1 "36:$c4:10:success"
assert_result "the newest created success is live" "$workdir/missed-inactive" 0 "prod-us: live ${c4:0:12}, contains: yes"

# A status from another creator on top of the live record changes nothing.
register_page "$workdir/foreign-status" prod-us 1 "52:$c4:59:inactive@someone-else,success" "51:$c1:10:success"
register_page "$workdir/foreign-status" prod-eu 1 "53:$c4:10:success"
assert_result "a foreign status on the live record is ignored" "$workdir/foreign-status" 0 "prod-us: live ${c4:0:12}, contains: yes"

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

# A full page of foreign statuses can bury the trusted success, so the record is unknown and the
# older live record must not count.
buried=$(printf 'inactive@someone-else,%.0s' $(seq 1 100))
register_page "$workdir/buried" prod-us 1 "62:$c1:59:${buried%,}" "61:$c4:10:success"
register_page "$workdir/buried" prod-eu 1 "63:$c4:10:success"
assert_result "a status page full of foreign statuses holds the release" "$workdir/buried" 3 "prod-us: no live deployment found"

# Final records never change, so a second poll does not read their statuses again.
register_page "$workdir/cached" prod-us 1 "71:$c4:30:failure" "72:$c4:20:inactive,success" "73:$c1:10:success"
register_page "$workdir/cached" prod-eu 1 "74:$c4:10:success"
# The waiter's deadline is a whole second, so a 1 second timeout ends after one poll whenever that
# poll crosses a second boundary. 3 seconds leaves room for a second poll after the 1 second sleep.
CASE_TIMEOUT_SECONDS=3 assert_result "a held release polls more than once" "$workdir/cached" 3 "prod-us: live ${c1:0:12}, contains: no"
for id in 71 72; do
    reads=$(grep -c "deployments_${id}_statuses" "$workdir/cached/calls")
    polls=$(grep -c "deployments_73_statuses" "$workdir/cached/calls")
    if [ "$reads" -ne 1 ] || [ "$polls" -lt 2 ]; then
        echo "FAIL: final record $id read $reads times over $polls polls"
        exit 1
    fi
done
echo "ok: final records are read once"

register_page "$workdir/api-failure" prod-us 1 "15:$c4:10:success"
touch "$workdir/api-failure/repos_PostHog_posthog_deployments_environment_prod-eu_task_deploy_per_page_30_page_1.fail"
assert_result "an API failure is not read as deployed" "$workdir/api-failure" 1 "prod-eu: GitHub API request failed"

echo "Backend deploy wait regression cases passed."
