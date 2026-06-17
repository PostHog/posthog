#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
target="${CLI_RELEASE_SMOKE_TARGET:-$(rustc -vV | sed -n 's/^host: //p')}"
dist_bin="${DIST_BIN:-dist}"
local_manifest="${CLI_RELEASE_SMOKE_MANIFEST:-/tmp/posthog-cli-local-dist-manifest.json}"
global_manifest="${CLI_RELEASE_SMOKE_GLOBAL_MANIFEST:-/tmp/posthog-cli-local-dist-global-manifest.json}"
python_bin="${PYTHON:-python3}"
server_port="${CLI_RELEASE_SMOKE_PORT:-8765}"

if ! command -v "$dist_bin" >/dev/null 2>&1; then
    cat >&2 <<'EOF'
cargo-dist is required for the release artifact smoke test.

Install the pinned version from dist-workspace.toml, for example:

    cargo install cargo-dist --version 0.32.0 --locked

Or set DIST_BIN=/path/to/dist.
EOF
    exit 1
fi

if ! command -v "$python_bin" >/dev/null 2>&1; then
    echo "python3 is required to serve local cargo-dist artifacts during the smoke test." >&2
    exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to check the local artifact server during the smoke test." >&2
    exit 1
fi

echo "Building API CLI release bundle..."
pnpm --dir "$repo_root/services/mcp" run build:cli:release
test -s "$repo_root/cli/lib/posthog-api-cli.mjs"

common_dist_args=()

if [[ "${CLI_RELEASE_SMOKE_ALLOW_DIRTY:-}" == "1" ]]; then
    common_dist_args+=(--allow-dirty)
fi

if [[ -n "${CLI_RELEASE_SMOKE_TAG:-}" ]]; then
    common_dist_args+=(--tag "$CLI_RELEASE_SMOKE_TAG")
fi

local_dist_args=(
    build
    --artifacts=local
    --target "$target"
    --print=linkage
    --output-format=json
    "${common_dist_args[@]}"
)

echo "Building cargo-dist local artifact for $target..."
"$dist_bin" "${local_dist_args[@]}" > "$local_manifest"

archive="$repo_root/target/distrib/posthog-cli-$target.tar.gz"
if [[ ! -f "$archive" ]]; then
    echo "Expected archive not found: $archive" >&2
    exit 1
fi

echo "Checking archive contains the API CLI bundle..."
tar -tzf "$archive" | grep -qx "posthog-cli-$target/lib/posthog-api-cli.mjs"

tmpdir="$(mktemp -d)"
server_pid=""
cleanup() {
    if [[ -n "$server_pid" ]]; then
        kill "$server_pid" >/dev/null 2>&1 || true
        wait "$server_pid" >/dev/null 2>&1 || true
    fi
    rm -rf "$tmpdir"
}
trap cleanup EXIT
mkdir -p "$tmpdir/home" "$tmpdir/unpack"

tar -xzf "$archive" --strip-components 1 -C "$tmpdir/unpack"
test -s "$tmpdir/unpack/lib/posthog-api-cli.mjs"

echo "Running packaged posthog-cli api --agent-help..."
if ! HOME="$tmpdir/home" "$tmpdir/unpack/posthog-cli" api --agent-help > "$tmpdir/agent-help.txt" 2> "$tmpdir/agent-help.err"; then
    cat "$tmpdir/agent-help.err" >&2
    exit 1
fi
grep -q "# PostHog API guide for agents" "$tmpdir/agent-help.txt"

global_dist_args=(
    build
    --artifacts=global
    --output-format=json
    "${common_dist_args[@]}"
)

echo "Building cargo-dist installer artifacts..."
"$dist_bin" "${global_dist_args[@]}" > "$global_manifest"

installer="$repo_root/target/distrib/posthog-cli-installer.sh"
if [[ ! -s "$installer" ]]; then
    echo "Expected shell installer not found: $installer" >&2
    exit 1
fi

echo "Serving local cargo-dist artifacts on http://127.0.0.1:$server_port..."
"$python_bin" -m http.server "$server_port" --bind 127.0.0.1 --directory "$repo_root/target/distrib" > "$tmpdir/http-server.log" 2>&1 &
server_pid=$!
server_url="http://127.0.0.1:$server_port"
server_ready=0
for _ in {1..50}; do
    if curl -fsSI "$server_url/$(basename "$archive")" >/dev/null 2>&1; then
        server_ready=1
        break
    fi
    if ! kill -0 "$server_pid" >/dev/null 2>&1; then
        cat "$tmpdir/http-server.log" >&2
        exit 1
    fi
    sleep 0.1
done
if [[ "$server_ready" != "1" ]]; then
    cat "$tmpdir/http-server.log" >&2
    echo "Timed out waiting for local artifact server. Set CLI_RELEASE_SMOKE_PORT to try a different port." >&2
    exit 1
fi

mkdir -p "$tmpdir/installed-home" "$tmpdir/installed"

echo "Running generated shell installer from local artifacts..."
if ! HOME="$tmpdir/installed-home" \
    INSTALLER_DOWNLOAD_URL="$server_url" \
    CARGO_DIST_FORCE_INSTALL_DIR="$tmpdir/installed" \
    INSTALLER_NO_MODIFY_PATH=1 \
    POSTHOG_CLI_DISABLE_UPDATE=1 \
    sh "$installer" --no-modify-path > "$tmpdir/installer.out" 2> "$tmpdir/installer.err"; then
    cat "$tmpdir/installer.out" >&2
    cat "$tmpdir/installer.err" >&2
    exit 1
fi

test -x "$tmpdir/installed/posthog-cli"

echo "Running installed posthog-cli api --agent-help..."
if ! HOME="$tmpdir/installed-home" "$tmpdir/installed/posthog-cli" api --agent-help > "$tmpdir/installed-agent-help.txt" 2> "$tmpdir/installed-agent-help.err"; then
    cat "$tmpdir/installed-agent-help.err" >&2
    exit 1
fi
grep -q "# PostHog API guide for agents" "$tmpdir/installed-agent-help.txt"

if [[ ! -s "$tmpdir/installed/lib/posthog-api-cli.mjs" ]]; then
    shopt -s nullglob
    materialized_bundles=("$tmpdir/installed-home/.posthog/api-cli"/*/posthog-api-cli.mjs)
    if [[ "${#materialized_bundles[@]}" -eq 0 ]]; then
        echo "Installed CLI worked, but no adjacent or materialized API CLI bundle was found." >&2
        exit 1
    fi
fi

echo "Release artifact smoke test passed: $archive"
echo "Packaged CLI available at: $repo_root/target/distrib/posthog-cli-$target/posthog-cli"
echo "Note: this smoke test does not replace any posthog-cli already on your PATH."
