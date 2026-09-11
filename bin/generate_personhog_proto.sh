#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROTO_DIR="$REPO_ROOT/proto"
OUT_DIR="$REPO_ROOT/posthog/personhog_client/proto/generated"

python -c "import grpc_tools" 2>/dev/null || { echo "Error: grpcio-tools is not installed. Run: uv sync" >&2; exit 1; }

echo "Cleaning old generated files..."
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

mapfile -d '' PROTO_FILES < <(find "$PROTO_DIR/personhog/service" "$PROTO_DIR/personhog/types" -name '*.proto' -print0)

echo "Generating Python protobuf and gRPC stubs..."
python -m grpc_tools.protoc \
    --proto_path="$PROTO_DIR" \
    --python_out="$OUT_DIR" \
    --pyi_out="$OUT_DIR" \
    --grpc_python_out="$OUT_DIR" \
    "${PROTO_FILES[@]}"

echo "Rewriting imports as relative..."
python "$SCRIPT_DIR/helpers/relativize_proto_imports.py" "$OUT_DIR"

echo "Linting and formatting generated files..."
ruff check --fix --quiet "$OUT_DIR"
ruff format --quiet "$OUT_DIR"

echo "Done. Generated files are in $OUT_DIR"
