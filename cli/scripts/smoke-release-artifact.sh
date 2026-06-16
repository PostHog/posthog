#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
target="${CLI_RELEASE_SMOKE_TARGET:-$(rustc -vV | sed -n 's/^host: //p')}"
dist_bin="${DIST_BIN:-dist}"
manifest="${CLI_RELEASE_SMOKE_MANIFEST:-/tmp/posthog-cli-local-dist-manifest.json}"

if ! command -v "$dist_bin" >/dev/null 2>&1; then
    cat >&2 <<'EOF'
cargo-dist is required for the release artifact smoke test.

Install the pinned version from dist-workspace.toml, for example:

    cargo install cargo-dist --version 0.32.0 --locked

Or set DIST_BIN=/path/to/dist.
EOF
    exit 1
fi

echo "Building API CLI release bundle..."
pnpm --dir "$repo_root/services/mcp" run build:cli:release
test -s "$repo_root/cli/lib/posthog-api-cli.mjs"

dist_args=(
    build
    --artifacts=local
    --target "$target"
    --print=linkage
    --output-format=json
)

if [[ "${CLI_RELEASE_SMOKE_ALLOW_DIRTY:-}" == "1" ]]; then
    dist_args+=(--allow-dirty)
fi

if [[ -n "${CLI_RELEASE_SMOKE_TAG:-}" ]]; then
    dist_args+=(--tag "$CLI_RELEASE_SMOKE_TAG")
fi

echo "Building cargo-dist local artifact for $target..."
"$dist_bin" "${dist_args[@]}" > "$manifest"

archive="$repo_root/target/distrib/posthog-cli-$target.tar.gz"
if [[ ! -f "$archive" ]]; then
    echo "Expected archive not found: $archive" >&2
    exit 1
fi

echo "Checking archive contains the API CLI bundle..."
tar -tzf "$archive" | grep -qx "posthog-cli-$target/lib/posthog-api-cli.mjs"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
mkdir -p "$tmpdir/home" "$tmpdir/unpack"

tar -xzf "$archive" --strip-components 1 -C "$tmpdir/unpack"
test -s "$tmpdir/unpack/lib/posthog-api-cli.mjs"

echo "Running packaged posthog-cli api --agent-help..."
if ! HOME="$tmpdir/home" "$tmpdir/unpack/posthog-cli" api --agent-help > "$tmpdir/agent-help.txt" 2> "$tmpdir/agent-help.err"; then
    cat "$tmpdir/agent-help.err" >&2
    exit 1
fi
grep -q "# PostHog API guide for agents" "$tmpdir/agent-help.txt"

echo "Release artifact smoke test passed: $archive"
echo "Packaged CLI available at: $repo_root/target/distrib/posthog-cli-$target/posthog-cli"
echo "Note: this smoke test does not replace any posthog-cli already on your PATH."
