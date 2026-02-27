#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROTO_DIR="$REPO_ROOT/proto"
OUT_DIR="$REPO_ROOT/posthog/personhog_client/proto/generated"

for cmd in buf protol; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is not installed." >&2
        exit 1
    fi
done

echo "Cleaning old generated files..."
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

echo "Generating Python protobuf and gRPC stubs..."
(cd "$PROTO_DIR" && buf generate --path personhog)

echo "Rewriting imports with protoletariat..."
protol \
    --create-package \
    --in-place \
    --python-out "$OUT_DIR" \
    buf "$PROTO_DIR"

echo "Done. Generated files are in $OUT_DIR"
