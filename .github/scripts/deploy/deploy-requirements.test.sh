#!/usr/bin/env bash
set -euo pipefail

reader="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/wait-for-deploy-requirements.sh"

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# gh stub: prints the fixture registered for the requested path and 404s on anything else.
fake_bin="$workdir/bin"
mkdir -p "$fake_bin" "$workdir/fixtures"
cat >"$fake_bin/gh" <<'STUB'
#!/usr/bin/env bash
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
if [ -f "$GH_FIXTURE_DIR/$slug.json" ]; then
    cat "$GH_FIXTURE_DIR/$slug.json"
else
    echo "stubbed 404 for $path" >&2
    exit 1
fi
STUB
chmod +x "$fake_bin/gh"

commit=2222222222222222222222222222222222222222
echo '{"status":"ahead"}' >"$workdir/fixtures/repos_PostHog_posthog_compare_$commit...master.json"
echo '[]' >"$workdir/fixtures/repos_PostHog_posthog_deployments_environment_prod-us_task_deploy_per_page_30_page_1.json"

failures=0
# Runs the reader on a manifest and checks its exit code and whether it called GitHub.
expect() {
    local name="$1" manifest="$2" expected_exit="$3" expected_calls="$4" actual_exit=0 calls
    rm -f "$workdir/fixtures/calls"
    printf '%s' "$manifest" >"$workdir/manifest.json"
    PATH="$fake_bin:$PATH" GH_FIXTURE_DIR="$workdir/fixtures" REPOSITORY=PostHog/posthog \
        ENVIRONMENTS=prod-us TIMEOUT_SECONDS=0 INTERVAL_SECONDS=0 \
        "$reader" "$workdir/manifest.json" >/dev/null 2>&1 || actual_exit=$?
    calls=$([ -f "$workdir/fixtures/calls" ] && echo yes || echo no)
    if [ "$actual_exit" != "$expected_exit" ] || [ "$calls" != "$expected_calls" ]; then
        echo "FAIL $name: exit $actual_exit (want $expected_exit), GitHub calls $calls (want $expected_calls)"
        failures=$((failures + 1))
    else
        echo "ok   $name"
    fi
}

requirement="{\"kind\":\"django_deploy\",\"commit\":\"$commit\"}"
expect "missing manifest" "" 1 no
expect "unknown schema_version" "{\"schema_version\":2,\"requirements\":[$requirement]}" 1 no
expect "unknown kind next to a known one" "{\"schema_version\":1,\"requirements\":[$requirement,{\"kind\":\"sqlx\",\"database\":\"persons\",\"versions\":[1]}]}" 1 no
expect "short commit" '{"schema_version":1,"requirements":[{"kind":"django_deploy","commit":"2222"}]}' 1 no
expect "no requirements" '{"schema_version":1,"requirements":[]}' 0 no
expect "Django not deployed yet" "{\"schema_version\":1,\"requirements\":[$requirement]}" 3 yes

[ "$failures" -eq 0 ] || exit 1
