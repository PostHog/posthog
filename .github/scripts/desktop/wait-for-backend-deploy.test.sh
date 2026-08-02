#!/usr/bin/env bash
set -euo pipefail

waiter="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/wait-for-backend-deploy.sh"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

fake_bin="$workdir/bin"
fixtures="$workdir/fixtures"
mkdir -p "$fake_bin" "$fixtures"
cat >"$fake_bin/gh" <<'EOF'
#!/usr/bin/env bash
slug=$(printf '%s' "${2:?}" | tr '/?&=' '____')
if [ -f "$GH_FIXTURE_DIR/$slug.json" ]; then
    cat "$GH_FIXTURE_DIR/$slug.json"
else
    echo '{}'
fi
EOF
chmod +x "$fake_bin/gh"

deployed_us="dddd0000dddd0000dddd0000dddd0000dddd0000"
deployed_eu="eeee0000eeee0000eeee0000eeee0000eeee0000"

register_env() {
    local env="$1" deployed="$2"
    # Newest deployment (id 2) never succeeded; the scan must fall through to
    # the older one (id 1) that did.
    cat >"$fixtures/repos_PostHog_posthog_deployments_environment_${env}_per_page_100_page_1.json" <<JSON
[{"id": 2, "ref": "not-the-one"}, {"id": 1, "ref": "$deployed"}]
JSON
}
register_env prod-us "$deployed_us"
register_env prod-eu "$deployed_eu"
echo '[{"state": "pending"}, {"state": "inactive"}]' >"$fixtures/repos_PostHog_posthog_deployments_2_statuses.json"
echo '[{"state": "in_progress"}, {"state": "success"}, {"state": "inactive"}]' >"$fixtures/repos_PostHog_posthog_deployments_1_statuses.json"

register_compare() {
    echo "{\"status\": \"$3\"}" >"$fixtures/repos_PostHog_posthog_compare_${1}...${2}.json"
}

check() {
    local name="$1" expected_status="$2" needle="$3" required="$4" output status
    shift 4
    set +e
    output=$(env PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$fixtures" REPOSITORY="PostHog/posthog" \
        POLL_SECONDS=1 TIMEOUT_SECONDS=0 REQUIRED_SHAS="$required" "$@" "$waiter" 2>&1)
    status=$?
    set -e
    if [ "$status" -ne "$expected_status" ] || ! grep -Fq "$needle" <<<"$output"; then
        echo "FAIL: $name (exit $status, expected $expected_status)"
        awk '{print "  | " $0}' <<<"$output"
        exit 1
    fi
    echo "ok: $name"
}

check "empty required set passes immediately" 0 "nothing to wait for" ""

both_deployed="1111000011110000111100001111000011110000"
register_compare "$both_deployed" "$deployed_us" ahead
register_compare "$both_deployed" "$deployed_eu" identical
check "sha inside both prod deploys passes" 0 "All required backend SHAs are deployed" "$both_deployed"

one_env="2222000022220000222200002222000022220000"
register_compare "$one_env" "$deployed_us" ahead
register_compare "$one_env" "$deployed_eu" behind
check "sha missing from one env blocks until timeout" 1 "Timed out" "$one_env"

unknown="3333000033330000333300003333000033330000"
register_compare "$unknown" "$deployed_us" ahead
check "compare API error blocks instead of passing" 1 "Timed out" "$unknown"

check "env with no successful deploy blocks" 1 "no successful deployment found" "$both_deployed" \
    ENVIRONMENTS="prod-empty"

echo "Backend deploy waiter regression cases passed."
