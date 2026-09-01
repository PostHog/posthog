#!/usr/bin/env bash
# Prints the sccache remote cache namespace for a Cargo.lock.
#
# sccache keys every compile on rustc, the source files, the extern rlibs and
# the static archives a crate bundles, so an ordinary dependency bump does not
# need a fresh namespace. The namespace only rotates when a crate that builds
# or binds a native library changes version, which is the one class of change
# that has produced link errors against stale artifacts.
set -euo pipefail

lock=${1:?usage: cache-key-prefix.sh <path/to/Cargo.lock>}

native_crate_versions=$(
    grep -A1 -E '^name = "([^"]*-sys|openssl-src|ring)"$' "$lock" \
        | grep -E '^(name|version) = ' \
        | paste -d ' ' - - \
        | sort
)

printf 'cargo-native-%s\n' "$(printf '%s\n' "$native_crate_versions" | sha256sum | cut -c1-16)"
