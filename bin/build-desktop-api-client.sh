#!/usr/bin/env bash
# Regenerates the desktop app's typed API client from frontend/tmp/openapi.json.
#
# Locally, a missing toolchain or a generator error leaves generated.ts unchanged,
# prints a warning and exits 0, so `hogli build:openapi` works without the desktop
# install. In CI both fail. Backend CI overwrites any hand edit to generated.ts
# with the generator output, and reviewer routing and the desktop coupling check
# skip the file because of that. A skipped regen would let a hand edit through.

set -uo pipefail

package_dir="products/desktop/packages/api-client"
generated="$package_dir/src/generated.ts"

fail() {
    if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
        echo "::error title=Desktop API client not regenerated::$1"
        exit 1
    fi
    echo "Warning: $1" >&2
    exit 0
}

# Run pnpm from inside the desktop workspace so it uses that workspace's pnpm version.
if ! (cd "$package_dir" && pnpm exec typed-openapi --version) >/dev/null 2>&1; then
    fail "The desktop API client generator is not installed, so $generated was not regenerated. Backend CI regenerates it on pull requests. To run it locally, install it with: pnpm --dir products/desktop install"
fi

backup=$(mktemp)
cp "$generated" "$backup"
# The generator can fail after typed-openapi has written an unformatted file, so restore the last good copy.
if ! (cd "$package_dir" && pnpm run generate-client); then
    cp "$backup" "$generated"
    rm -f "$backup"
    fail "The desktop API client generator failed, so $generated was not regenerated. See the log above. Released desktop apps depend on every endpoint and schema in $package_dir/endpoint-allowlist.json. Remove an endpoint or schema from the allowlist in a desktop PR first, then remove it from the backend."
fi
rm -f "$backup"
