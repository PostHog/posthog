#!/bin/sh
# Builds hog-worker for every target in Docker, on any machine that runs Linux containers:
#   release/build-worker.sh --version 1.2.3 --target linux-arm64 --target darwin-arm64
# The arguments go to release/build-worker.ts, which lists them. The builds land in
# dist/release/bin/<target>/, next to the hog binaries release/compile.ts writes.

set -eu

hog_root=$(cd "$(dirname "$0")/.." && pwd)
image=hog-worker-cross

docker build --tag "$image" --file "$hog_root/release/worker-cross.Dockerfile" "$hog_root/release"

# The Windows C runtime and SDK cargo-xwin downloads stay in a Docker volume, which unpacks them far
# faster than a folder shared with macOS and keeps them for the next local run.
docker run --rm \
    --volume "$hog_root:/hog" \
    --volume hog-worker-cross-xwin:/root/.cache/cargo-xwin \
    --workdir /hog \
    "$image" bun release/build-worker.ts "$@"
