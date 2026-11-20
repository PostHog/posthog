#!/usr/bin/env bash
# posthog-cli builds posthog-symbol-processing from rust/common/symbol_processing, and the
# posthog-cli package on crates.io resolves the version named in cli/Cargo.toml from crates.io.
# A release is only the same program from both sources when that version is published and holds
# the source in this checkout. This check stops a release for which that is not true, before any
# artifact ships.
set -euo pipefail

CRATE=posthog-symbol-processing
RETRY_ARGS=(--retry 5 --retry-all-errors --retry-max-time 60 --connect-timeout 10)
# crates.io asks automated clients to identify themselves.
USER_AGENT="posthog-cli-release-check (https://github.com/PostHog/posthog)"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
crate_dir="$repo_root/rust/common/symbol_processing"
registry="${CRATES_IO_URL:-https://crates.io}"
downloads="${CRATES_IO_DOWNLOAD_URL:-https://static.crates.io}"

fail() {
    echo "::error::$1" >&2
    exit 1
}

local_version=$(grep '^version = ' "$crate_dir/Cargo.toml" | head -1 | sed 's/version = "\(.*\)"/\1/')
required_version=$(sed -n -E "s|^$CRATE = \{ path = \"[^\"]+\", version = \"([^\"]+)\" \}$|\1|p" "$repo_root/cli/Cargo.toml")

if [ -z "$required_version" ]; then
    fail "cli/Cargo.toml does not name $CRATE by path and version, so the published posthog-cli cannot be checked against this source."
fi

if [ "$required_version" != "$local_version" ]; then
    fail "cli/Cargo.toml requires $CRATE $required_version, and rust/common/symbol_processing is $local_version. A posthog-cli from crates.io would not build the source this release was tested with. Set the requirement in cli/Cargo.toml to $local_version."
fi

pending=$(find "$crate_dir/.sampo/changesets" -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
if [ "$pending" -gt 0 ]; then
    fail "$CRATE has $pending unreleased changeset(s). Merge its release pull request and wait for the 'Release $CRATE' workflow to publish, then release posthog-cli."
fi

status=$(curl -sS "${RETRY_ARGS[@]}" -o /dev/null -w '%{http_code}' -A "$USER_AGENT" "$registry/api/v1/crates/$CRATE/$local_version")
if [ "$status" = "404" ]; then
    fail "$CRATE $local_version is not on crates.io, and posthog-cli needs it there to publish. Wait for the 'Release $CRATE' workflow to publish it, then run this release again."
fi
if [ "$status" != "200" ]; then
    fail "crates.io answered HTTP $status for $CRATE $local_version, so the release cannot tell whether the crate is published. Run this release again."
fi

scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT

curl -fsSL "${RETRY_ARGS[@]}" -A "$USER_AGENT" -o "$scratch/crate.tar.gz" "$downloads/crates/$CRATE/$CRATE-$local_version.crate"
tar -xzf "$scratch/crate.tar.gz" -C "$scratch"

if ! diff -r "$scratch/$CRATE-$local_version/src" "$crate_dir/src" >"$scratch/source.diff"; then
    cat "$scratch/source.diff" >&2
    fail "$CRATE $local_version on crates.io does not hold the source in rust/common/symbol_processing/src. The crate changed without a release. Add a changeset for it, merge its release pull request, then release posthog-cli."
fi

echo "$CRATE $local_version is on crates.io with the source in this checkout."
