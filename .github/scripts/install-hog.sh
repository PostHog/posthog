#!/usr/bin/env bash
# Installs a pinned hog release for a CI job and prints the path to the binary.
#
# The version and the archive checksums are pinned here, because the chunk and release IDs hog injects
# into frontend/dist ship in the image: hog must not be mutable remote code. To upgrade, set HOG_VERSION
# and copy the linux-x64 and linux-arm64 checksums from
# https://releases.posthog.com/hog/v<version>/manifest.json.
set -euo pipefail

readonly HOG_VERSION=0.1.0

case "$(uname -m)" in
    x86_64) target=linux-x64 sha256=811999531f50e991cbb3f19944e2d18a050dcca5880db7924c7456f7fa374565 ;;
    aarch64 | arm64) target=linux-arm64 sha256=c3dd9ea837775981280b174d5d9ed8b6d7100a37b6039e7c6939a7a6d9e7ebd4 ;;
    *)
        echo "There is no pinned hog build for $(uname -m)." >&2
        exit 1
        ;;
esac

dir="${RUNNER_TEMP:-$(mktemp -d)}/hog-$HOG_VERSION"
mkdir -p "$dir"
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 -o "$dir/hog.tar.gz" \
    "https://releases.posthog.com/hog/v$HOG_VERSION/hog-$target.tar.gz"
echo "$sha256  $dir/hog.tar.gz" | sha256sum -c - >&2
tar -xzf "$dir/hog.tar.gz" -C "$dir" hog
echo "$dir/hog"
