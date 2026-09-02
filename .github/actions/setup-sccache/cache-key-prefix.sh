#!/usr/bin/env bash
# Prints the sccache remote cache namespace for a Cargo.lock: a hash of the
# versions of the crates that build or bind native libraries. sccache keys each
# compile on rustc, the sources and the extern rlibs, so a pure-Rust bump needs
# no new namespace; only stale native artifacts have produced link errors.
set -euo pipefail

lock=${1:?usage: cache-key-prefix.sh <path/to/Cargo.lock>}

native_crate_hash=$(
    grep -A1 -E '^name = "([^"]*-sys|openssl-src|ring)"$' "$lock" \
        | grep -E '^(name|version) = ' \
        | paste -d ' ' - - \
        | LC_ALL=C sort \
        | sha256sum \
        | cut -c1-16
)

printf 'cargo-native-%s\n' "$native_crate_hash"
