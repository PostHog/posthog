#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROTO_DIR="$REPO_ROOT/proto"
OUT_DIR="$REPO_ROOT/posthog/personhog_client/proto/generated"

if ! python -c "import grpc_tools" &>/dev/null; then
    echo "Error: grpcio-tools is not installed. Run: uv pip install grpcio-tools" >&2
    exit 1
fi

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

echo "Adding __init__.py files..."
find "$OUT_DIR" -type d -exec touch {}/__init__.py \;

echo "Done. Generated files are in $OUT_DIR"
