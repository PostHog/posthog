#!/usr/bin/env bash
# Regenerates the desktop app's typed API client from frontend/tmp/openapi.json.
#
# Always exits 0. A missing toolchain or a generator error leaves generated.ts
# unchanged and prints a warning, so `hogli build:openapi` and Backend CI keep
# working for backend changes the desktop client does not depend on.

set -uo pipefail

package_dir="products/desktop/packages/api-client"
generated="$package_dir/src/generated.ts"

warn() {
    if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
        echo "::warning title=Desktop API client not regenerated::$1"
    else
        echo "Warning: $1" >&2
    fi
}

# Run pnpm from inside the desktop workspace so it uses that workspace's pnpm version.
if ! (cd "$package_dir" && pnpm exec typed-openapi --version) >/dev/null 2>&1; then
    warn "The desktop API client generator is not installed, so $generated was not regenerated. Backend CI regenerates it on pull requests. To run it locally, install it with: pnpm --dir products/desktop install"
    exit 0
fi

backup=$(mktemp)
cp "$generated" "$backup"
# The generator can fail after typed-openapi has written an unformatted file, so restore the last good copy.
if ! (cd "$package_dir" && pnpm run generate-client); then
    cp "$backup" "$generated"
    warn "The desktop API client generator failed, so $generated was not regenerated. See the log above. An endpoint or schema that left the OpenAPI schema must be removed from $package_dir/endpoint-allowlist.json."
fi
rm -f "$backup"
exit 0
