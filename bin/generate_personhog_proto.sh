#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROTO_DIR="$REPO_ROOT/proto"
OUT_DIR="$REPO_ROOT/posthog/personhog_client/proto/generated"

for cmd in grpc_tools protoletariat; do
    if ! python -c "import $cmd" &>/dev/null; then
        echo "Error: $cmd is not installed. Run: uv sync" >&2
        exit 1
    fi
done

echo "Cleaning old generated files..."
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

PROTO_FILES=$(find "$PROTO_DIR/personhog" -name '*.proto')

echo "Generating Python protobuf and gRPC stubs..."
python -m grpc_tools.protoc \
    --proto_path="$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --pyi_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    $PROTO_FILES

echo "Rewriting imports with protoletariat..."
FDSET=$(mktemp)
python -m grpc_tools.protoc \
    --proto_path="$PROTO_DIR" \
    --descriptor_set_out="$FDSET" \
    --include_imports \
    $PROTO_FILES
protol \
    --create-package \
    --in-place \
    --python-out "$OUT_DIR" \
    raw "$FDSET"
rm -f "$FDSET"

echo "Linting and formatting generated files..."
ruff check --fix --quiet "$OUT_DIR"
ruff format --quiet "$OUT_DIR"

echo "Done. Generated files are in $OUT_DIR"
