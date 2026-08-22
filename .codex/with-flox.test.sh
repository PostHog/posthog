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
    local fake_repo="$test_root/$name"

    mkdir -p \
        "$fake_repo/.codex" \
        "$fake_repo/.flox/env" \
        "$fake_repo/bin" \
        "$fake_repo/fake-bin" \
        "$fake_repo/home" \
        "$fake_repo/tools/phrocs"
    cp "$source_root/.codex/with-flox" "$fake_repo/.codex/with-flox"
    cp "$source_root/.codex/run-with-dotenv.py" "$fake_repo/.codex/run-with-dotenv.py"
    : > "$fake_repo/.flox/env/manifest.toml"
    : > "$fake_repo/.flox/env/on-activate.sh"
    : > "$fake_repo/bin/dev-sandbox"
    : > "$fake_repo/bin/dev-sandbox.sb"
    : > "$fake_repo/pnpm-lock.yaml"
    : > "$fake_repo/uv.lock"

    cat > "$fake_repo/fake-bin/flox" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ "${1:-}" != "activate" || "${2:-}" != "--dir" || "${4:-}" != "--" ]]; then
    echo "unexpected fake Flox arguments" >&2
    exit 2
fi

repo_root="$3"
shift 4
mkdir -p "$repo_root/.flox/cache/venv/bin"
printf 'invoked\n' >> "$repo_root/.flox/cache/flox-invocations"
export DEBUG=1
export FLOX_ENV_CACHE="$repo_root/.flox/cache"
export PATH="/usr/bin:/bin"
exec "$@"
EOF
    chmod +x "$fake_repo/fake-bin/flox"

    printf '%s' "$fake_repo"
}

run_with_flox() {
    local fake_repo="$1"
    local environment=(
        env -i
        "HOME=$fake_repo/home"
        LANG=C
        "PATH=$fake_repo/fake-bin:/usr/bin:/bin"
        SHELL=/bin/bash
        "TMPDIR=${TMPDIR:-/tmp}"
        USER=codex-test
    )
    shift
    if [[ -n "${TEST_CODEX_SANDBOX:-}" ]]; then
        environment+=("CODEX_SANDBOX=$TEST_CODEX_SANDBOX")
    fi
    "${environment[@]}" "$fake_repo/.codex/with-flox" "$@"
}

auto_prepare_repo="$(make_fake_repo auto-prepare)"
output="$(run_with_flox "$auto_prepare_repo" /bin/bash -c 'printf %s "$DEBUG"')"
[[ "$output" == "1" ]] || fail "missing cache was not prepared before the command ran"
[[ -f "$auto_prepare_repo/.flox/cache/codex-env" ]] || fail "setup did not create codex-env"
[[ "$(wc -l < "$auto_prepare_repo/.flox/cache/flox-invocations")" -eq 1 ]] || fail "initial setup did not run exactly once"

run_with_flox "$auto_prepare_repo" /usr/bin/true
[[ "$(wc -l < "$auto_prepare_repo/.flox/cache/flox-invocations")" -eq 1 ]] || fail "valid cache caused unnecessary setup"

printf 'changed\n' >> "$auto_prepare_repo/.flox/env/manifest.toml"
run_with_flox "$auto_prepare_repo" /usr/bin/true
[[ "$(wc -l < "$auto_prepare_repo/.flox/cache/flox-invocations")" -eq 2 ]] || fail "stale cache was not rebuilt"

sandbox_repo="$(make_fake_repo sandbox)"
set +e
sandbox_output="$(TEST_CODEX_SANDBOX=seatbelt run_with_flox "$sandbox_repo" /usr/bin/true 2>&1)"
sandbox_status=$?
set -e
[[ "$sandbox_status" -eq 77 ]] || fail "sandbox setup returned $sandbox_status instead of 77"
[[ "$sandbox_output" == *"requires elevated execution"* ]] || fail "sandbox setup did not request elevated execution"
[[ ! -e "$sandbox_repo/.flox/cache/flox-invocations" ]] || fail "sandbox setup invoked Flox"

echo "Codex Flox wrapper regression cases passed."
