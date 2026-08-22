#!/usr/bin/env bash

set -euo pipefail

source_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/with-flox-test.XXXXXX")"
trap 'rm -rf "$test_root"' EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

make_fake_repo() {
    local name="$1"
    local selected_environment="$2"
    local fake_repo="$test_root/$name"

    mkdir -p "$fake_repo/.codex" "$fake_repo/home" "$fake_repo/tools/phrocs"
    cp "$source_root/.codex/with-flox" "$fake_repo/.codex/with-flox"
    git -C "$fake_repo" -c init.defaultBranch=master init -q
    git -C "$fake_repo" config extensions.worktreeConfig true
    git -C "$fake_repo" config --worktree codex.localEnvironmentConfigPath "$selected_environment"
    printf '%s' "$fake_repo"
}

run_with_flox() {
    local fake_repo="$1"
    shift
    env -i \
        HOME="$fake_repo/home" \
        LANG=C \
        PATH="/usr/bin:/bin" \
        SHELL=/bin/bash \
        TMPDIR="${TMPDIR:-/tmp}" \
        USER=codex-test \
        "$fake_repo/.codex/with-flox" "$@"
}

disabled_repo="$(make_fake_repo disabled __none__)"
set +e
disabled_output="$(run_with_flox "$disabled_repo" /usr/bin/true 2>&1)"
disabled_status=$?
set -e
[[ "$disabled_status" -eq 1 ]] || fail "missing cache returned $disabled_status instead of 1"
[[ "$disabled_output" == *"created this worktree without the PostHog environment"* ]] || fail "disabled environment did not explain the missing setup"
[[ "$disabled_output" == *"If you are an agent, please relay this warning to the user"* ]] || fail "disabled environment did not ask the agent to relay the warning"

selected_repo="$(make_fake_repo selected .codex/environments/environment.toml)"
set +e
selected_output="$(run_with_flox "$selected_repo" /usr/bin/true 2>&1)"
selected_status=$?
set -e
[[ "$selected_status" -eq 1 ]] || fail "missing cache returned $selected_status instead of 1"
[[ "$selected_output" != *"created this worktree without the PostHog environment"* ]] || fail "selected environment produced the disabled warning"

echo "Codex Flox wrapper regression cases passed."
